"""Stage 5: Queue and Channel Rationalization."""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from .decision_log import DecisionLog
from .model import (
    ClientRole,
    EdgeType,
    PortDirection,
    TopologyClient,
    TopologyEdge,
    TopologyModel,
    TopologyPort,
)
from .naming import NamingEngine


class Rationalizer:
    """Standardize naming, wire complete message paths, decide alias retention."""

    def __init__(self, decision_log: DecisionLog):
        self.log = decision_log

    def run(self, model: TopologyModel) -> TopologyModel:
        flows = self._identify_message_flows(model)
        self._wire_flows(model, flows)
        self._prune_unused_aliases(model)
        self._standardize_channel_names(model)
        return model

    def _identify_message_flows(
        self, model: TopologyModel
    ) -> List[Tuple[TopologyClient, TopologyClient, str]]:
        """Identify producer→consumer message flows from port connections.

        Returns list of (producer_client, consumer_client, queue_base_name).
        """
        flows = []

        # Build app_id → client mapping
        app_clients: Dict[str, TopologyClient] = {}
        for client in model.clients.values():
            app_clients[client.app_id] = client

        # Scan remote ports: a remote port on producer's QM targeting consumer's QM
        for port in model.ports.values():
            if port.direction != PortDirection.REMOTE:
                continue
            if not port.remote_node_id:
                continue

            # Find the producer (client on this port's node)
            producer = None
            for client in model.clients.values():
                if (
                    client.home_node_id == port.node_id
                    and client.role in (ClientRole.PRODUCER, ClientRole.BOTH)
                    and port.id in client.connected_ports
                ):
                    producer = client
                    break

            if not producer:
                continue

            # Find the consumer on the remote QM
            consumer = None
            for client in model.clients.values():
                if (
                    client.home_node_id == port.remote_node_id
                    and client.role in (ClientRole.CONSUMER, ClientRole.BOTH)
                ):
                    consumer = client
                    break

            if consumer and producer.id != consumer.id:
                flows.append((producer, consumer, port.name))

        self.log.record(
            stage="rationalization",
            action="identify_flows",
            subject_type="model",
            subject_id="all",
            description=f"Identified {len(flows)} producer→consumer message flows",
            reason="Flow analysis for message path wiring",
            evidence={"flow_count": len(flows)},
        )

        return flows

    def _wire_flows(
        self,
        model: TopologyModel,
        flows: List[Tuple[TopologyClient, TopologyClient, str]],
    ) -> None:
        """Wire complete message paths based on topology."""
        wired = 0

        for producer, consumer, queue_name in flows:
            prod_qm = producer.home_node_id
            cons_qm = consumer.home_node_id

            if prod_qm == cons_qm:
                # Same QM: local queue only
                self._ensure_local_queue(model, prod_qm, queue_name, producer, consumer)
                wired += 1
                continue

            # Different QMs: route via hub-spoke
            prod_node = model.nodes.get(prod_qm)
            cons_node = model.nodes.get(cons_qm)

            if not prod_node or not cons_node:
                continue

            prod_comm = prod_node.community_id
            cons_comm = cons_node.community_id

            if prod_comm == cons_comm:
                # Same community: route via hub
                hub = self._find_hub(model, prod_comm)
                if hub and hub != prod_qm and hub != cons_qm:
                    self._wire_through_hub(
                        model, producer, consumer, queue_name, prod_qm, hub, cons_qm
                    )
                else:
                    # Direct if no hub or one endpoint IS the hub
                    self._wire_direct(model, producer, consumer, queue_name, prod_qm, cons_qm)
            else:
                # Cross-community: route via both hubs
                prod_hub = self._find_hub(model, prod_comm)
                cons_hub = self._find_hub(model, cons_comm)
                if prod_hub and cons_hub and prod_hub != cons_hub:
                    self._wire_cross_community(
                        model, producer, consumer, queue_name,
                        prod_qm, prod_hub, cons_hub, cons_qm,
                    )
                else:
                    self._wire_direct(model, producer, consumer, queue_name, prod_qm, cons_qm)

            wired += 1

        self.log.record(
            stage="rationalization",
            action="wire_flows",
            subject_type="model",
            subject_id="all",
            description=f"Wired {wired} message flows with complete routing paths",
            reason="Ensure all message paths have proper queue/channel/xmit objects",
            evidence={"wired_count": wired},
        )

    def _find_hub(self, model: TopologyModel, community_id: Optional[int]) -> Optional[str]:
        if community_id is None:
            return None
        for node in model.nodes.values():
            if node.community_id == community_id and node.is_hub:
                return node.id
        return None

    def _ensure_local_queue(
        self,
        model: TopologyModel,
        qm: str,
        queue_name: str,
        producer: TopologyClient,
        consumer: TopologyClient,
    ) -> None:
        """Ensure a local queue exists for same-QM communication."""
        port_id = f"{qm}.{queue_name}"
        if port_id not in model.ports:
            model.ports[port_id] = TopologyPort(
                id=port_id,
                node_id=qm,
                name=queue_name,
                direction=PortDirection.LOCAL,
            )
        if port_id not in producer.connected_ports:
            producer.connected_ports.append(port_id)
        if port_id not in consumer.connected_ports:
            consumer.connected_ports.append(port_id)

    def _wire_direct(
        self,
        model: TopologyModel,
        producer: TopologyClient,
        consumer: TopologyClient,
        queue_name: str,
        prod_qm: str,
        cons_qm: str,
    ) -> None:
        """Wire a direct producer-QM → consumer-QM path."""
        xmit_name = NamingEngine.xmit_queue(cons_qm)

        # Remote queue on producer's QM
        rq_id = f"{prod_qm}.{queue_name}"
        if rq_id not in model.ports:
            model.ports[rq_id] = TopologyPort(
                id=rq_id,
                node_id=prod_qm,
                name=queue_name,
                direction=PortDirection.REMOTE,
                remote_queue=queue_name,
                remote_node_id=cons_qm,
                xmit_queue=xmit_name,
            )
        if rq_id not in producer.connected_ports:
            producer.connected_ports.append(rq_id)

        # Local queue on consumer's QM
        lq_id = f"{cons_qm}.{queue_name}"
        if lq_id not in model.ports:
            model.ports[lq_id] = TopologyPort(
                id=lq_id,
                node_id=cons_qm,
                name=queue_name,
                direction=PortDirection.LOCAL,
            )
        if lq_id not in consumer.connected_ports:
            consumer.connected_ports.append(lq_id)

        # Ensure channel exists
        self._ensure_edge(model, prod_qm, cons_qm)

    def _wire_through_hub(
        self,
        model: TopologyModel,
        producer: TopologyClient,
        consumer: TopologyClient,
        queue_name: str,
        prod_qm: str,
        hub_qm: str,
        cons_qm: str,
    ) -> None:
        """Wire producer-QM → hub → consumer-QM."""
        # Producer QM: remote queue → xmit → channel to hub
        xmit_to_hub = NamingEngine.xmit_queue(hub_qm)
        rq_id = f"{prod_qm}.{queue_name}"
        if rq_id not in model.ports:
            model.ports[rq_id] = TopologyPort(
                id=rq_id,
                node_id=prod_qm,
                name=queue_name,
                direction=PortDirection.REMOTE,
                remote_queue=queue_name,
                remote_node_id=hub_qm,
                xmit_queue=xmit_to_hub,
            )
        if rq_id not in producer.connected_ports:
            producer.connected_ports.append(rq_id)

        # Hub: local queue (receives from producer QM) + remote queue (forwards to consumer QM)
        hub_local_id = f"{hub_qm}.{queue_name}"
        if hub_local_id not in model.ports:
            model.ports[hub_local_id] = TopologyPort(
                id=hub_local_id,
                node_id=hub_qm,
                name=queue_name,
                direction=PortDirection.LOCAL,
            )

        hub_fwd_name = f"{queue_name}.FWD"
        hub_fwd_id = f"{hub_qm}.{hub_fwd_name}"
        xmit_to_cons = NamingEngine.xmit_queue(cons_qm)
        if hub_fwd_id not in model.ports:
            model.ports[hub_fwd_id] = TopologyPort(
                id=hub_fwd_id,
                node_id=hub_qm,
                name=hub_fwd_name,
                direction=PortDirection.REMOTE,
                remote_queue=queue_name,
                remote_node_id=cons_qm,
                xmit_queue=xmit_to_cons,
            )

        # Consumer QM: local queue
        lq_id = f"{cons_qm}.{queue_name}"
        if lq_id not in model.ports:
            model.ports[lq_id] = TopologyPort(
                id=lq_id,
                node_id=cons_qm,
                name=queue_name,
                direction=PortDirection.LOCAL,
            )
        if lq_id not in consumer.connected_ports:
            consumer.connected_ports.append(lq_id)

        # Ensure channels
        self._ensure_edge(model, prod_qm, hub_qm)
        self._ensure_edge(model, hub_qm, cons_qm)

    def _wire_cross_community(
        self,
        model: TopologyModel,
        producer: TopologyClient,
        consumer: TopologyClient,
        queue_name: str,
        prod_qm: str,
        prod_hub: str,
        cons_hub: str,
        cons_qm: str,
    ) -> None:
        """Wire producer-QM → producer-hub → consumer-hub → consumer-QM."""
        # Simplify: chain through two hubs
        # Producer QM → Producer Hub
        if prod_qm != prod_hub:
            self._wire_direct(model, producer, consumer, queue_name, prod_qm, prod_hub)

        # Producer Hub → Consumer Hub (backbone)
        self._ensure_edge(model, prod_hub, cons_hub)

        # Consumer Hub → Consumer QM
        if cons_qm != cons_hub:
            # Create forwarding on consumer hub
            hub_fwd_name = f"{queue_name}.FWD"
            hub_fwd_id = f"{cons_hub}.{hub_fwd_name}"
            xmit_to_cons = NamingEngine.xmit_queue(cons_qm)
            if hub_fwd_id not in model.ports:
                model.ports[hub_fwd_id] = TopologyPort(
                    id=hub_fwd_id,
                    node_id=cons_hub,
                    name=hub_fwd_name,
                    direction=PortDirection.REMOTE,
                    remote_queue=queue_name,
                    remote_node_id=cons_qm,
                    xmit_queue=xmit_to_cons,
                )

            # Local queue on consumer QM
            lq_id = f"{cons_qm}.{queue_name}"
            if lq_id not in model.ports:
                model.ports[lq_id] = TopologyPort(
                    id=lq_id,
                    node_id=cons_qm,
                    name=queue_name,
                    direction=PortDirection.LOCAL,
                )
            if lq_id not in consumer.connected_ports:
                consumer.connected_ports.append(lq_id)

            self._ensure_edge(model, cons_hub, cons_qm)

    def _ensure_edge(self, model: TopologyModel, source: str, target: str) -> None:
        """Ensure a channel edge exists from source to target."""
        edge_id = NamingEngine.edge_id(source, target)
        if edge_id not in model.edges:
            model.edges[edge_id] = TopologyEdge(
                id=edge_id,
                source_node_id=source,
                target_node_id=target,
                edge_type=EdgeType.CHANNEL,
                name=NamingEngine.channel_sender(source, target),
                metadata={"channel_type": "sender", "created_by": "rationalizer"},
            )

    def _prune_unused_aliases(self, model: TopologyModel) -> None:
        """Remove aliases that don't serve an active routing purpose."""
        client_ports = set()
        for c in model.clients.values():
            client_ports.update(c.connected_ports)

        pruned = 0
        to_remove = []
        for pid, port in model.ports.items():
            if port.direction == PortDirection.ALIAS and pid not in client_ports:
                to_remove.append(pid)

        for pid in to_remove:
            del model.ports[pid]
            pruned += 1

        if pruned > 0:
            self.log.record(
                stage="rationalization",
                action="prune_aliases",
                subject_type="model",
                subject_id="all",
                description=f"Pruned {pruned} unused alias queues",
                reason="Aliases not serving any active routing purpose",
                evidence={"pruned_count": pruned},
            )

    def _standardize_channel_names(self, model: TopologyModel) -> None:
        """Ensure all channel names follow the naming convention."""
        renamed = 0
        for edge in model.edges.values():
            expected = NamingEngine.channel_sender(
                edge.source_node_id, edge.target_node_id
            )
            if edge.name != expected:
                old_name = edge.name
                edge.name = expected
                renamed += 1

        if renamed > 0:
            self.log.record(
                stage="rationalization",
                action="standardize_names",
                subject_type="model",
                subject_id="all",
                description=f"Standardized {renamed} channel names to convention",
                reason="Enforce {FROM_QM}.TO.{TO_QM} naming pattern",
                evidence={"renamed_count": renamed},
            )
