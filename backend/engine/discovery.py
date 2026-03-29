"""Stage 0: Graph Discovery - infer channels from queue metadata."""

from __future__ import annotations

from typing import Set, Tuple

from .decision_log import DecisionLog
from .model import EdgeType, PortDirection, TopologyEdge, TopologyModel
from .naming import NamingEngine


class GraphDiscovery:
    """Build the as-is graph by inferring channels from remote queue references."""

    def __init__(self, decision_log: DecisionLog):
        self.log = decision_log

    def run(self, model: TopologyModel) -> TopologyModel:
        """Infer channels from remote_q_mgr_name references in ports."""
        channel_pairs: Set[Tuple[str, str]] = set()

        # Scan all ports for remote references
        for port in model.ports.values():
            if port.direction in (PortDirection.REMOTE, PortDirection.ALIAS):
                source_qm = port.node_id
                target_qm = port.remote_node_id

                if (
                    target_qm
                    and target_qm in model.nodes
                    and source_qm != target_qm
                ):
                    channel_pairs.add((source_qm, target_qm))

        # Also infer from xmit queue names (format: APPID.TARGETQM or TARGETQM)
        for port in model.ports.values():
            if port.xmit_queue and port.direction == PortDirection.REMOTE:
                source_qm = port.node_id
                # xmit queue name often encodes the target QM
                # Common patterns: "OK.WQ26" → target is WQ26
                parts = port.xmit_queue.split(".")
                for part in parts:
                    if part in model.nodes and part != source_qm:
                        channel_pairs.add((source_qm, part))

        # Create bidirectional channel edges
        created = 0
        for source_qm, target_qm in sorted(channel_pairs):
            # Sender channel: source → target
            sender_name = NamingEngine.channel_sender(source_qm, target_qm)
            sender_id = NamingEngine.edge_id(source_qm, target_qm)

            if sender_id not in model.edges:
                model.edges[sender_id] = TopologyEdge(
                    id=sender_id,
                    source_node_id=source_qm,
                    target_node_id=target_qm,
                    edge_type=EdgeType.CHANNEL,
                    name=sender_name,
                    metadata={"channel_type": "sender", "inferred": True},
                )
                created += 1

            # Receiver channel (reverse): target → source
            # Only create if the reverse doesn't already exist from another pair
            receiver_id = NamingEngine.edge_id(target_qm, source_qm)
            if receiver_id not in model.edges and (target_qm, source_qm) not in channel_pairs:
                receiver_name = NamingEngine.channel_sender(target_qm, source_qm)
                model.edges[receiver_id] = TopologyEdge(
                    id=receiver_id,
                    source_node_id=target_qm,
                    target_node_id=source_qm,
                    edge_type=EdgeType.CHANNEL,
                    name=receiver_name,
                    metadata={"channel_type": "receiver", "inferred": True},
                )
                created += 1

        self.log.record(
            stage="graph_discovery",
            action="infer_channels",
            subject_type="model",
            subject_id="all_edges",
            description=(
                f"Inferred {created} channels from {len(channel_pairs)} "
                f"unique QM-to-QM communication pairs"
            ),
            reason="Channels are not in input data; inferred from remote queue references",
            evidence={
                "channel_pairs": [
                    {"source": s, "target": t} for s, t in sorted(channel_pairs)
                ],
                "total_edges_created": created,
            },
        )

        # Classify ports
        local_count = sum(1 for p in model.ports.values() if p.direction == PortDirection.LOCAL)
        remote_count = sum(1 for p in model.ports.values() if p.direction == PortDirection.REMOTE)
        alias_count = sum(1 for p in model.ports.values() if p.direction == PortDirection.ALIAS)
        xmit_count = sum(1 for p in model.ports.values() if p.direction == PortDirection.TRANSMISSION)

        self.log.record(
            stage="graph_discovery",
            action="classify_ports",
            subject_type="model",
            subject_id="all_ports",
            description=(
                f"Port classification: {local_count} local, {remote_count} remote, "
                f"{alias_count} alias, {xmit_count} transmission"
            ),
            reason="Port type distribution for analysis",
            evidence={
                "local": local_count,
                "remote": remote_count,
                "alias": alias_count,
                "transmission": xmit_count,
            },
        )

        return model
