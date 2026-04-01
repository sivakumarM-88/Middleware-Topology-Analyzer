"""Stage 4: Hub Election and Spoke Wiring."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Set, Tuple

import networkx as nx

from .decision_log import DecisionLog
from .model import EdgeType, TopologyEdge, TopologyModel
from .naming import NamingEngine


class HubElector:
    """Elect hubs per community and rewire mesh channels to hub-spoke topology."""

    def __init__(
        self,
        decision_log: DecisionLog,
        centrality_weight: float = 0.6,
        business_weight: float = 0.4,
        min_community_size: int = 3,
    ):
        self.log = decision_log
        self.centrality_weight = centrality_weight
        self.business_weight = business_weight
        self.min_community_size = min_community_size

    def run(self, model: TopologyModel) -> TopologyModel:
        communities = model.get_communities()
        ug = model.get_undirected_graph()

        # ── Phase 1: Snapshot cross-community pairs BEFORE rewiring ──
        # Rewiring removes direct edges, so we must capture needs first.
        cross_community_pairs: Set[Tuple[int, int]] = set()
        for edge in model.edges.values():
            src = model.nodes.get(edge.source_node_id)
            tgt = model.nodes.get(edge.target_node_id)
            if (
                src and tgt
                and src.community_id is not None
                and tgt.community_id is not None
                and src.community_id != tgt.community_id
            ):
                cross_community_pairs.add((src.community_id, tgt.community_id))

        # ── Phase 2: Elect hubs ──
        hubs_elected = 0
        edges_removed = 0
        edges_created = 0
        hub_map: Dict[int, str] = {}  # community_id → hub_id

        for cid, members in communities.items():
            if len(members) < self.min_community_size:
                self.log.record(
                    stage="hub_election",
                    action="skip_small_community",
                    subject_type="community",
                    subject_id=str(cid),
                    description=(
                        f"Community {cid} has {len(members)} members "
                        f"(< {self.min_community_size}), skipping hub-spoke"
                    ),
                    reason="Community too small to benefit from hub-spoke topology",
                    evidence={"community_id": cid, "size": len(members)},
                )
                continue

            sub = ug.subgraph(members)
            centrality = nx.betweenness_centrality(sub)
            biz_scores = self._compute_business_scores(model, members)

            scores: Dict[str, float] = {}
            for nid in members:
                c_norm = centrality.get(nid, 0.0)
                b_norm = biz_scores.get(nid, 0.0)
                scores[nid] = (
                    self.centrality_weight * c_norm
                    + self.business_weight * b_norm
                )

            hub_id = max(scores, key=scores.get)
            model.nodes[hub_id].is_hub = True
            hub_map[cid] = hub_id
            hubs_elected += 1

            self.log.record(
                stage="hub_election",
                action="elect_hub",
                subject_type="node",
                subject_id=hub_id,
                description=f"Elected {hub_id} as hub for community {cid}",
                reason=(
                    f"Highest combined score: "
                    f"centrality={centrality.get(hub_id, 0):.3f}, "
                    f"business={biz_scores.get(hub_id, 0):.3f}, "
                    f"total={scores[hub_id]:.3f}"
                ),
                evidence={
                    "community_id": cid,
                    "hub": hub_id,
                    "all_scores": {
                        nid: {
                            "centrality": round(centrality.get(nid, 0), 4),
                            "business": round(biz_scores.get(nid, 0), 4),
                            "total": round(scores[nid], 4),
                        }
                        for nid in members
                    },
                },
            )

        # ── Phase 3: Rewire each hub-spoke community ──
        all_spokes: Set[str] = set()
        for cid, hub_id in hub_map.items():
            members = communities[cid]
            spokes = [nid for nid in members if nid != hub_id]
            all_spokes.update(spokes)
            r, c = self._rewire_community(model, hub_id, spokes, cid)
            edges_removed += r
            edges_created += c

        # ── Phase 4: Create backbone + reconnect small communities ──
        backbone = self._create_backbone(
            model, hub_map, cross_community_pairs, communities
        )

        self.log.record(
            stage="hub_election",
            action="hub_election_summary",
            subject_type="model",
            subject_id="all",
            description=(
                f"Elected {hubs_elected} hubs, removed {edges_removed} mesh channels, "
                f"created {edges_created} spoke channels, {backbone} backbone channels"
            ),
            reason="Hub-spoke transformation complete",
            evidence={
                "hubs_elected": hubs_elected,
                "edges_removed": edges_removed,
                "edges_created": edges_created,
                "backbone_channels": backbone,
            },
        )

        return model

    def _compute_business_scores(
        self, model: TopologyModel, members: List[str]
    ) -> Dict[str, float]:
        """Score each node by business criticality (0-1 normalized)."""
        raw: Dict[str, float] = {}
        for nid in members:
            node = model.nodes[nid]
            bm = node.business_metadata
            score = 0.0

            # PCI apps add weight
            score += bm.get("pci_apps_count", 0) * 3.0

            # Critical payment apps add weight
            score += bm.get("critical_payment_apps_count", 0) * 5.0

            # Lower TRTC (faster recovery) = more suitable as hub
            trtc_classes = bm.get("trtc_classes", [])
            for trtc in trtc_classes:
                if "0-30 Minutes" in str(trtc):
                    score += 4.0
                elif "2 Hours" in str(trtc):
                    score += 2.0
                elif "4:01" in str(trtc):
                    score += 1.0

            # More connected apps = more central
            clients_on_node = len(model.get_clients_on_node(nid))
            score += clients_on_node * 1.0

            raw[nid] = score

        # Normalize to 0-1
        max_score = max(raw.values()) if raw else 1.0
        if max_score == 0:
            max_score = 1.0
        return {nid: s / max_score for nid, s in raw.items()}

    def _rewire_community(
        self,
        model: TopologyModel,
        hub_id: str,
        spokes: List[str],
        community_id: int,
    ) -> Tuple[int, int]:
        """Replace ALL direct spoke edges with spoke↔hub channels.

        Removes every edge from/to a spoke (except spoke↔hub), including
        cross-community direct edges.  Cross-community traffic will be
        handled by backbone hub-to-hub channels created in Phase 4.
        """
        spoke_set = set(spokes)
        removed = 0
        created = 0

        # Remove ALL edges involving spokes, EXCEPT spoke↔hub
        to_remove = []
        for eid, edge in model.edges.items():
            src_is_spoke = edge.source_node_id in spoke_set
            tgt_is_spoke = edge.target_node_id in spoke_set
            if not src_is_spoke and not tgt_is_spoke:
                continue
            # Keep existing spoke→hub and hub→spoke edges
            if src_is_spoke and edge.target_node_id == hub_id:
                continue
            if tgt_is_spoke and edge.source_node_id == hub_id:
                continue
            to_remove.append(eid)

        for eid in to_remove:
            del model.edges[eid]
            removed += 1

        if removed > 0:
            self.log.record(
                stage="hub_election",
                action="remove_spoke_channels",
                subject_type="community",
                subject_id=str(community_id),
                description=(
                    f"Removed {removed} direct edges involving spokes "
                    f"in community {community_id} (hub={hub_id})"
                ),
                reason="All spoke traffic must route through hub",
                evidence={
                    "community_id": community_id,
                    "hub": hub_id,
                    "edges_removed": removed,
                },
            )

        # Create spoke↔hub edges unconditionally (overwrite if pre-existing
        # to ensure correct metadata)
        for spoke_id in spokes:
            # Spoke → Hub
            s2h_id = NamingEngine.edge_id(spoke_id, hub_id)
            model.edges[s2h_id] = TopologyEdge(
                id=s2h_id,
                source_node_id=spoke_id,
                target_node_id=hub_id,
                edge_type=EdgeType.CHANNEL,
                name=NamingEngine.channel_sender(spoke_id, hub_id),
                metadata={
                    "channel_type": "sender",
                    "topology": "spoke_to_hub",
                    "community_id": community_id,
                },
            )
            created += 1

            # Hub → Spoke
            h2s_id = NamingEngine.edge_id(hub_id, spoke_id)
            model.edges[h2s_id] = TopologyEdge(
                id=h2s_id,
                source_node_id=hub_id,
                target_node_id=spoke_id,
                edge_type=EdgeType.CHANNEL,
                name=NamingEngine.channel_sender(hub_id, spoke_id),
                metadata={
                    "channel_type": "sender",
                    "topology": "hub_to_spoke",
                    "community_id": community_id,
                },
            )
            created += 1

        return removed, created

    def _create_backbone(
        self,
        model: TopologyModel,
        hub_map: Dict[int, str],
        cross_community_pairs: Set[Tuple[int, int]],
        communities: Dict[int, List[str]],
    ) -> int:
        """Create backbone channels for cross-community traffic.

        Uses the pre-captured cross_community_pairs (snapshotted before
        rewiring removed direct edges).

        Three cases:
        - Both communities have hubs → hub↔hub backbone
        - One has a hub, other is small → small-community nodes ↔ hub
        - Neither has a hub → preserve existing direct edges (untouched)
        """
        created = 0

        for comm_a, comm_b in cross_community_pairs:
            hub_a = hub_map.get(comm_a)
            hub_b = hub_map.get(comm_b)

            if hub_a and hub_b and hub_a != hub_b:
                # Both communities have hubs — create hub-to-hub backbone
                created += self._ensure_backbone_edge(
                    model, hub_a, hub_b, "backbone", comm_a, comm_b
                )
                created += self._ensure_backbone_edge(
                    model, hub_b, hub_a, "backbone", comm_b, comm_a
                )

            elif hub_a and not hub_b:
                # Community B is small (no hub).  Its nodes may have lost
                # edges to spokes in community A during rewiring.
                # Connect B's members directly to hub_a.
                for nid in communities.get(comm_b, []):
                    if nid == hub_a:
                        continue
                    created += self._ensure_backbone_edge(
                        model, nid, hub_a, "small_to_hub", comm_b, comm_a
                    )
                    created += self._ensure_backbone_edge(
                        model, hub_a, nid, "hub_to_small", comm_a, comm_b
                    )

            elif hub_b and not hub_a:
                # Community A is small (no hub) — mirror of above
                for nid in communities.get(comm_a, []):
                    if nid == hub_b:
                        continue
                    created += self._ensure_backbone_edge(
                        model, nid, hub_b, "small_to_hub", comm_a, comm_b
                    )
                    created += self._ensure_backbone_edge(
                        model, hub_b, nid, "hub_to_small", comm_b, comm_a
                    )
            # else: neither has a hub (both small) — direct edges were
            # never removed, so connectivity is preserved.

        if created > 0:
            self.log.record(
                stage="hub_election",
                action="create_backbone",
                subject_type="model",
                subject_id="backbone",
                description=f"Created {created} backbone / cross-community channels",
                reason="Cross-community traffic requires hub-to-hub connectivity",
                evidence={
                    "backbone_channels": created,
                    "cross_community_pairs": [
                        list(p) for p in cross_community_pairs
                    ],
                },
            )

        return created

    def _ensure_backbone_edge(
        self,
        model: TopologyModel,
        source: str,
        target: str,
        topology_type: str,
        from_community: int,
        to_community: int,
    ) -> int:
        """Create a backbone/cross-community edge if it doesn't exist."""
        eid = NamingEngine.edge_id(source, target)
        if eid in model.edges:
            return 0
        model.edges[eid] = TopologyEdge(
            id=eid,
            source_node_id=source,
            target_node_id=target,
            edge_type=EdgeType.CHANNEL,
            name=NamingEngine.channel_sender(source, target),
            metadata={
                "channel_type": "sender",
                "topology": topology_type,
                "from_community": from_community,
                "to_community": to_community,
            },
        )
        return 1
