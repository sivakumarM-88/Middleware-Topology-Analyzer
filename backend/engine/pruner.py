"""Stage 2: Dead Object Pruning - remove unused MQ objects."""

from __future__ import annotations

from .decision_log import DecisionLog
from .model import PortDirection, TopologyModel


class DeadObjectPruner:
    """Remove orphan QMs, queues, aliases, and dead channels."""

    def __init__(self, decision_log: DecisionLog):
        self.log = decision_log

    def run(self, model: TopologyModel) -> TopologyModel:
        removed_nodes = self._prune_orphan_nodes(model)
        removed_ports = self._prune_orphan_ports(model)
        removed_aliases = self._prune_dead_aliases(model)
        removed_edges = self._prune_dead_edges(model)

        self.log.record(
            stage="dead_object_pruning",
            action="prune_summary",
            subject_type="model",
            subject_id="all",
            description=(
                f"Pruned {removed_nodes} orphan QMs, {removed_ports} orphan queues, "
                f"{removed_aliases} dead aliases, {removed_edges} dead channels"
            ),
            reason="Remove unused objects to reduce complexity",
            evidence={
                "removed_nodes": removed_nodes,
                "removed_ports": removed_ports,
                "removed_aliases": removed_aliases,
                "removed_edges": removed_edges,
            },
        )

        return model

    def _prune_orphan_nodes(self, model: TopologyModel) -> int:
        """Remove QMs with no clients and no active channels."""
        client_nodes = {c.home_node_id for c in model.clients.values()}
        edge_nodes = set()
        for e in model.edges.values():
            edge_nodes.add(e.source_node_id)
            edge_nodes.add(e.target_node_id)

        orphans = [
            nid for nid in model.nodes
            if nid not in client_nodes and nid not in edge_nodes
        ]

        for nid in orphans:
            self.log.record(
                stage="dead_object_pruning",
                action="remove_orphan_node",
                subject_type="node",
                subject_id=nid,
                description=f"Removed orphan QM {nid}: no clients, no channels",
                reason="QM has no applications and no active channels",
                evidence={"node_id": nid},
            )
            del model.nodes[nid]

        return len(orphans)

    def _prune_orphan_ports(self, model: TopologyModel) -> int:
        """Remove queues not referenced by any client."""
        client_ports = set()
        for c in model.clients.values():
            client_ports.update(c.connected_ports)

        # Also keep ports that are on active nodes (they might be part of routing)
        active_nodes = set(model.nodes.keys())

        orphans = [
            pid for pid, port in model.ports.items()
            if pid not in client_ports
            and port.node_id not in active_nodes
        ]

        for pid in orphans:
            self.log.record(
                stage="dead_object_pruning",
                action="remove_orphan_port",
                subject_type="port",
                subject_id=pid,
                description=f"Removed orphan queue {pid}: no client reference, node removed",
                reason="Queue has no producer/consumer and its QM was removed",
            )
            del model.ports[pid]

        return len(orphans)

    def _prune_dead_aliases(self, model: TopologyModel) -> int:
        """Remove aliases that resolve to non-existent queues."""
        # Build a set of all existing queue names per node
        existing_queues = {
            (p.node_id, p.name)
            for p in model.ports.values()
            if p.direction != PortDirection.ALIAS
        }

        dead = []
        for pid, port in model.ports.items():
            if port.direction != PortDirection.ALIAS:
                continue
            # An alias should resolve to a queue on the same or remote node
            if port.remote_queue:
                target_node = port.remote_node_id or port.node_id
                if (target_node, port.remote_queue) not in existing_queues:
                    # Check if the target queue exists anywhere
                    found = any(
                        p.name == port.remote_queue
                        for p in model.ports.values()
                        if p.direction != PortDirection.ALIAS
                    )
                    if not found:
                        dead.append(pid)

        for pid in dead:
            self.log.record(
                stage="dead_object_pruning",
                action="remove_dead_alias",
                subject_type="port",
                subject_id=pid,
                description=f"Removed dead alias {pid}: target queue no longer exists",
                reason="Alias resolves to a removed queue",
            )
            del model.ports[pid]
            # Remove from client connections
            for client in model.clients.values():
                if pid in client.connected_ports:
                    client.connected_ports.remove(pid)

        return len(dead)

    def _prune_dead_edges(self, model: TopologyModel) -> int:
        """Remove channels where source or target QM no longer exists."""
        dead = [
            eid for eid, edge in model.edges.items()
            if edge.source_node_id not in model.nodes
            or edge.target_node_id not in model.nodes
        ]

        for eid in dead:
            edge = model.edges[eid]
            self.log.record(
                stage="dead_object_pruning",
                action="remove_dead_edge",
                subject_type="edge",
                subject_id=eid,
                description=(
                    f"Removed dead channel {edge.name}: "
                    f"endpoint QM no longer exists"
                ),
                reason="Channel source or target QM was removed",
                evidence={
                    "source": edge.source_node_id,
                    "target": edge.target_node_id,
                    "source_exists": edge.source_node_id in model.nodes,
                    "target_exists": edge.target_node_id in model.nodes,
                },
            )
            del model.edges[eid]

        return len(dead)
