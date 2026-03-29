"""Stage 3: Community Detection using Louvain algorithm."""

from __future__ import annotations

from collections import defaultdict

import community as community_louvain

from .decision_log import DecisionLog
from .model import TopologyModel


class CommunityDetector:
    """Detect communities of closely-connected QMs using Louvain."""

    def __init__(self, decision_log: DecisionLog):
        self.log = decision_log

    def run(self, model: TopologyModel) -> TopologyModel:
        ug = model.get_undirected_graph()

        if ug.number_of_nodes() == 0:
            self.log.record(
                stage="community_detection",
                action="skip",
                subject_type="model",
                subject_id="all",
                description="No nodes to cluster",
                reason="Empty graph",
            )
            return model

        # Run Louvain community detection
        partition = community_louvain.best_partition(ug, random_state=42)
        modularity = community_louvain.modularity(partition, ug)

        # Assign community IDs to nodes
        for node_id, comm_id in partition.items():
            if node_id in model.nodes:
                model.nodes[node_id].community_id = comm_id

        # Handle isolated nodes (no edges) — assign each to its own community
        max_comm = max(partition.values()) if partition else -1
        for node_id in model.nodes:
            if model.nodes[node_id].community_id is None:
                max_comm += 1
                model.nodes[node_id].community_id = max_comm

        # Build community summary
        communities = defaultdict(list)
        for node_id, node in model.nodes.items():
            communities[node.community_id].append(node_id)

        self.log.record(
            stage="community_detection",
            action="detect_communities",
            subject_type="model",
            subject_id="all",
            description=(
                f"Detected {len(communities)} communities via Louvain "
                f"(modularity={modularity:.3f})"
            ),
            reason="Group QMs that exchange most traffic internally",
            evidence={
                "community_count": len(communities),
                "modularity": round(modularity, 4),
                "communities": {
                    str(cid): members for cid, members in sorted(communities.items())
                },
                "community_sizes": {
                    str(cid): len(members)
                    for cid, members in sorted(communities.items())
                },
            },
        )

        # Log each community
        for cid, members in sorted(communities.items()):
            self.log.record(
                stage="community_detection",
                action="assign_community",
                subject_type="community",
                subject_id=str(cid),
                description=(
                    f"Community {cid}: {len(members)} QMs — {', '.join(members)}"
                ),
                reason="Louvain partitioning",
                evidence={"community_id": cid, "members": members},
            )

        return model
