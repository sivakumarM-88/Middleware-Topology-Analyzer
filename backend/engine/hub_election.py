"""Stage 4: Hub Election and Spoke Wiring."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Tuple

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

        hubs_elected = 0
        edges_removed = 0
        edges_created = 0

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

            # Compute betweenness centrality within this community
            sub = ug.subgraph(members)
            centrality = nx.betweenness_centrality(sub)

            # Compute business criticality score per node
            biz_scores = self._compute_business_scores(model, members)

            # Elect hub = argmax(centrality_weight * centrality + business_weight * biz)
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

            # Rewire: remove direct spoke-to-spoke channels, add spoke-to-hub
            spokes = [nid for nid in members if nid != hub_id]
            r, c = self._rewire_community(model, hub_id, spokes, cid)
            edges_removed += r
            edges_created += c

        # Create hub-to-hub backbone channels for cross-community traffic
        backbone = self._create_backbone(model, communities)

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
        """Remove spoke-to-spoke channels, add spoke-to-hub channels."""
        spoke_set = set(spokes)
        removed = 0
        created = 0

        # Remove direct spoke-to-spoke edges within this community
        to_remove = []
        for eid, edge in model.edges.items():
            if (
                edge.source_node_id in spoke_set
                and edge.target_node_id in spoke_set
            ):
                to_remove.append(eid)

        for eid in to_remove:
            edge = model.edges[eid]
            self.log.record(
                stage="hub_election",
                action="remove_spoke_channel",
                subject_type="edge",
                subject_id=eid,
                description=(
                    f"Removed spoke-to-spoke channel {edge.name} "
                    f"({edge.source_node_id} → {edge.target_node_id})"
                ),
                reason="Replaced by hub-spoke routing",
                evidence={"community_id": community_id},
            )
            del model.edges[eid]
            removed += 1

        # Create spoke → hub and hub → spoke channels
        for spoke_id in spokes:
            # Spoke → Hub
            s2h_id = NamingEngine.edge_id(spoke_id, hub_id)
            if s2h_id not in model.edges:
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
            if h2s_id not in model.edges:
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
        communities: Dict[int, List[str]],
    ) -> int:
        """Create hub-to-hub backbone channels for cross-community traffic."""
        hubs = model.get_hubs()
        if len(hubs) < 2:
            return 0

        created = 0
        # Check which hub pairs need backbone channels
        # (based on existing cross-community communication)
        hub_communities = {
            n.id: n.community_id
            for n in model.nodes.values()
            if n.is_hub
        }

        # Find all cross-community QM pairs that need connectivity
        cross_pairs = set()
        for edge in list(model.edges.values()):
            src_comm = model.nodes.get(edge.source_node_id, None)
            tgt_comm = model.nodes.get(edge.target_node_id, None)
            if (
                src_comm and tgt_comm
                and src_comm.community_id is not None
                and tgt_comm.community_id is not None
                and src_comm.community_id != tgt_comm.community_id
            ):
                cross_pairs.add((src_comm.community_id, tgt_comm.community_id))

        # For each cross-community pair, connect their hubs
        hub_by_comm = {}
        for hub_id in hubs:
            comm = model.nodes[hub_id].community_id
            hub_by_comm[comm] = hub_id

        for comm_a, comm_b in cross_pairs:
            hub_a = hub_by_comm.get(comm_a)
            hub_b = hub_by_comm.get(comm_b)
            if not hub_a or not hub_b:
                continue

            # Hub A → Hub B
            edge_id = NamingEngine.edge_id(hub_a, hub_b)
            if edge_id not in model.edges:
                model.edges[edge_id] = TopologyEdge(
                    id=edge_id,
                    source_node_id=hub_a,
                    target_node_id=hub_b,
                    edge_type=EdgeType.CHANNEL,
                    name=NamingEngine.channel_sender(hub_a, hub_b),
                    metadata={
                        "channel_type": "sender",
                        "topology": "backbone",
                        "from_community": comm_a,
                        "to_community": comm_b,
                    },
                )
                created += 1

            # Hub B → Hub A
            edge_id = NamingEngine.edge_id(hub_b, hub_a)
            if edge_id not in model.edges:
                model.edges[edge_id] = TopologyEdge(
                    id=edge_id,
                    source_node_id=hub_b,
                    target_node_id=hub_a,
                    edge_type=EdgeType.CHANNEL,
                    name=NamingEngine.channel_sender(hub_b, hub_a),
                    metadata={
                        "channel_type": "sender",
                        "topology": "backbone",
                        "from_community": comm_b,
                        "to_community": comm_a,
                    },
                )
                created += 1

        if created > 0:
            self.log.record(
                stage="hub_election",
                action="create_backbone",
                subject_type="model",
                subject_id="backbone",
                description=f"Created {created} hub-to-hub backbone channels",
                reason="Cross-community traffic requires hub-to-hub connectivity",
                evidence={
                    "backbone_channels": created,
                    "cross_community_pairs": [
                        list(p) for p in cross_pairs
                    ],
                },
            )

        return created
