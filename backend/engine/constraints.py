"""Stage 1: Constraint Enforcement - enforce 1-QM-per-app and 1-app-per-QM rules."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Set

from .decision_log import DecisionLog
from .model import (
    ClientRole,
    EdgeType,
    PortDirection,
    TopologyClient,
    TopologyEdge,
    TopologyModel,
    TopologyNode,
    TopologyPort,
)
from .naming import NamingEngine


class ConstraintEnforcer:
    """Enforce topology constraints: 1-QM-per-app AND 1-app-per-QM."""

    def __init__(self, decision_log: DecisionLog):
        self.log = decision_log

    def run(self, model: TopologyModel) -> TopologyModel:
        # Step 1: Consolidate apps that span multiple QMs
        model = self._consolidate_multi_qm_apps(model)
        # Step 2: Split QMs that host multiple apps (each app gets its own QM)
        model = self._split_shared_qms(model)
        return model

    # ── Step 1: Consolidate apps on multiple QMs ──────────────────────────

    def _consolidate_multi_qm_apps(self, model: TopologyModel) -> TopologyModel:
        """Ensure each app_id connects to exactly one queue manager."""
        app_clients: Dict[str, List[TopologyClient]] = defaultdict(list)
        for client in model.clients.values():
            app_clients[client.app_id].append(client)

        violations = {
            app_id: clients
            for app_id, clients in app_clients.items()
            if len(clients) > 1
        }

        if not violations:
            self.log.record(
                stage="constraint_enforcement",
                action="check_1qm_per_app",
                subject_type="model",
                subject_id="all_clients",
                description="No 1-QM-per-app violations found",
                reason="All apps already connect to exactly one QM",
            )
            return model

        migrated_count = 0
        for app_id, clients in violations.items():
            def score_client(c: TopologyClient) -> int:
                count = 0
                for pid in c.connected_ports:
                    port = model.ports.get(pid)
                    if port and port.direction != PortDirection.ALIAS:
                        count += 1
                return count

            primary = max(clients, key=score_client)
            others = [c for c in clients if c.id != primary.id]

            for other in others:
                old_qm = other.home_node_id
                new_qm = primary.home_node_id

                for port_id in list(other.connected_ports):
                    port = model.ports.get(port_id)
                    if port is None:
                        continue
                    if port.direction == PortDirection.ALIAS:
                        continue

                    new_port_id = f"{new_qm}.{port.name}"
                    if new_port_id not in model.ports:
                        model.ports[new_port_id] = TopologyPort(
                            id=new_port_id,
                            node_id=new_qm,
                            name=port.name,
                            direction=port.direction,
                            remote_queue=port.remote_queue,
                            remote_node_id=port.remote_node_id,
                            xmit_queue=port.xmit_queue,
                            metadata=dict(port.metadata),
                        )

                    if new_port_id not in primary.connected_ports:
                        primary.connected_ports.append(new_port_id)

                self.log.record(
                    stage="constraint_enforcement",
                    action="migrate_app",
                    subject_type="client",
                    subject_id=other.id,
                    description=(
                        f"Migrated app {app_id} from QM {old_qm} to {new_qm} "
                        f"(merged into {primary.id})"
                    ),
                    reason="1-QM-per-app constraint violated",
                    evidence={
                        "primary_client": primary.id,
                        "primary_score": score_client(primary),
                        "removed_client": other.id,
                        "removed_score": score_client(other),
                    },
                    from_state={"home_qm": old_qm},
                    to_state={"home_qm": new_qm},
                )
                del model.clients[other.id]
                migrated_count += 1

        self.log.record(
            stage="constraint_enforcement",
            action="consolidate_summary",
            subject_type="model",
            subject_id="all_clients",
            description=f"Resolved {len(violations)} multi-QM violations, migrated {migrated_count} client entries",
            reason="1-QM-per-app enforcement complete",
            evidence={
                "violations_found": len(violations),
                "migrations": migrated_count,
                "remaining_clients": len(model.clients),
            },
        )

        return model

    # ── Step 2: Split QMs hosting multiple apps ───────────────────────────

    def _split_shared_qms(self, model: TopologyModel) -> TopologyModel:
        """Split QMs with multiple apps so each app gets its own dedicated QM.

        Strategy: primary app (most connected ports) KEEPS the original QM.
        Each secondary app gets a NEW dedicated QM ({ORIGINAL_QM}_{APP_ID}).
        Shared local queues become cross-QM routing (remote + xmit + channels).
        """
        qm_apps: Dict[str, List[TopologyClient]] = defaultdict(list)
        for client in model.clients.values():
            qm_apps[client.home_node_id].append(client)

        shared_qms = {qm: apps for qm, apps in qm_apps.items() if len(apps) > 1}

        if not shared_qms:
            self.log.record(
                stage="constraint_enforcement",
                action="check_1app_per_qm",
                subject_type="model",
                subject_id="all_nodes",
                description="No shared-QM violations found",
                reason="All QMs already host exactly one app",
            )
            return model

        for qm_id, apps in shared_qms.items():
            original_node = model.nodes[qm_id]

            # Primary app keeps the original QM (most connected ports)
            primary = max(apps, key=lambda c: len(c.connected_ports))
            others = [a for a in apps if a.id != primary.id]

            # ── Pre-mutation snapshots ──
            primary_port_ids = set(primary.connected_ports)

            # ── Process each secondary app ──
            for app in others:
                app_port_ids = set(app.connected_ports)
                shared_port_ids = primary_port_ids & app_port_ids
                exclusive_port_ids = app_port_ids - primary_port_ids

                # Create new dedicated QM: {ORIGINAL_QM}_{APP_ID}
                new_qm_id = f"{qm_id}_{app.app_id}"
                model.nodes[new_qm_id] = TopologyNode(
                    id=new_qm_id,
                    name=f"QM for {app.app_name}",
                    node_type=original_node.node_type,
                    region=original_node.region,
                    business_metadata=dict(original_node.business_metadata),
                )

                new_port_ids: List[str] = []

                # Move exclusive ports to new QM
                for pid in exclusive_port_ids:
                    port = model.ports.get(pid)
                    if not port:
                        continue
                    new_pid = f"{new_qm_id}.{port.name}"
                    model.ports[new_pid] = TopologyPort(
                        id=new_pid,
                        node_id=new_qm_id,
                        name=port.name,
                        direction=port.direction,
                        remote_queue=port.remote_queue,
                        remote_node_id=port.remote_node_id,
                        xmit_queue=port.xmit_queue,
                        metadata=dict(port.metadata),
                    )
                    new_port_ids.append(new_pid)

                # ── Handle shared local queues: cross-QM routing ──
                xmit_to_new = NamingEngine.xmit_queue(new_qm_id)
                xmit_to_orig = NamingEngine.xmit_queue(qm_id)

                for pid in shared_port_ids:
                    port = model.ports.get(pid)
                    if not port:
                        continue

                    if port.direction == PortDirection.LOCAL:
                        # Local queue on new QM for the secondary app
                        new_local_pid = f"{new_qm_id}.{port.name}"
                        if new_local_pid not in model.ports:
                            model.ports[new_local_pid] = TopologyPort(
                                id=new_local_pid,
                                node_id=new_qm_id,
                                name=port.name,
                                direction=PortDirection.LOCAL,
                                metadata=dict(port.metadata),
                            )
                        new_port_ids.append(new_local_pid)

                        # Remote queue on original QM → new QM
                        rq_name = f"{port.name}.TO.{app.app_id}"
                        rq_pid = f"{qm_id}.{rq_name}"
                        if rq_pid not in model.ports:
                            model.ports[rq_pid] = TopologyPort(
                                id=rq_pid,
                                node_id=qm_id,
                                name=rq_name,
                                direction=PortDirection.REMOTE,
                                remote_queue=port.name,
                                remote_node_id=new_qm_id,
                                xmit_queue=xmit_to_new,
                                metadata=dict(port.metadata),
                            )

                        # Remote queue on new QM → original QM
                        rq_back_name = f"{port.name}.TO.{primary.app_id}"
                        rq_back_pid = f"{new_qm_id}.{rq_back_name}"
                        if rq_back_pid not in model.ports:
                            model.ports[rq_back_pid] = TopologyPort(
                                id=rq_back_pid,
                                node_id=new_qm_id,
                                name=rq_back_name,
                                direction=PortDirection.REMOTE,
                                remote_queue=port.name,
                                remote_node_id=qm_id,
                                xmit_queue=xmit_to_orig,
                                metadata=dict(port.metadata),
                            )
                    else:
                        # Non-local shared port: copy to new QM
                        new_pid = f"{new_qm_id}.{port.name}"
                        if new_pid not in model.ports:
                            model.ports[new_pid] = TopologyPort(
                                id=new_pid,
                                node_id=new_qm_id,
                                name=port.name,
                                direction=port.direction,
                                remote_queue=port.remote_queue,
                                remote_node_id=port.remote_node_id,
                                xmit_queue=port.xmit_queue,
                                metadata=dict(port.metadata),
                            )
                        new_port_ids.append(new_pid)

                # ── Create XMIT queue ports (TRANSMISSION) ──
                xmit_pid_orig = f"{qm_id}.XMITQ.{xmit_to_new}"
                if xmit_pid_orig not in model.ports:
                    model.ports[xmit_pid_orig] = TopologyPort(
                        id=xmit_pid_orig,
                        node_id=qm_id,
                        name=xmit_to_new,
                        direction=PortDirection.TRANSMISSION,
                        remote_node_id=new_qm_id,
                        metadata={"created_by": "qm_split"},
                    )

                xmit_pid_new = f"{new_qm_id}.XMITQ.{xmit_to_orig}"
                if xmit_pid_new not in model.ports:
                    model.ports[xmit_pid_new] = TopologyPort(
                        id=xmit_pid_new,
                        node_id=new_qm_id,
                        name=xmit_to_orig,
                        direction=PortDirection.TRANSMISSION,
                        remote_node_id=qm_id,
                        metadata={"created_by": "qm_split"},
                    )

                # ── Bidirectional channels between original and new QM ──
                fwd_id = NamingEngine.edge_id(qm_id, new_qm_id)
                if fwd_id not in model.edges:
                    model.edges[fwd_id] = TopologyEdge(
                        id=fwd_id,
                        source_node_id=qm_id,
                        target_node_id=new_qm_id,
                        edge_type=EdgeType.CHANNEL,
                        name=NamingEngine.channel_sender(qm_id, new_qm_id),
                        metadata={"channel_type": "sender", "created_by": "qm_split"},
                    )
                rev_id = NamingEngine.edge_id(new_qm_id, qm_id)
                if rev_id not in model.edges:
                    model.edges[rev_id] = TopologyEdge(
                        id=rev_id,
                        source_node_id=new_qm_id,
                        target_node_id=qm_id,
                        edge_type=EdgeType.CHANNEL,
                        name=NamingEngine.channel_sender(new_qm_id, qm_id),
                        metadata={"channel_type": "sender", "created_by": "qm_split"},
                    )

                # ── Update the client: new home QM, new port list ──
                old_client_id = app.id
                app.home_node_id = new_qm_id
                app.connected_ports = new_port_ids
                new_client_id = f"{app.app_id}@{new_qm_id}"
                app.id = new_client_id
                del model.clients[old_client_id]
                model.clients[new_client_id] = app

                self.log.record(
                    stage="constraint_enforcement",
                    action="split_shared_qm",
                    subject_type="node",
                    subject_id=new_qm_id,
                    description=(
                        f"Split QM {qm_id}: moved app {app.app_id} ({app.app_name}) "
                        f"to new dedicated QM {new_qm_id}. "
                        f"Primary app {primary.app_id} keeps original QM. "
                        f"Created channels for {len(shared_port_ids)} shared queues."
                    ),
                    reason="1-app-per-QM: each app must have its own dedicated queue manager",
                    evidence={
                        "original_qm": qm_id,
                        "new_qm": new_qm_id,
                        "primary_app": primary.app_id,
                        "moved_app": app.app_id,
                        "shared_queues": len(shared_port_ids),
                        "exclusive_queues": len(exclusive_port_ids),
                    },
                    from_state={"home_qm": qm_id, "apps_on_qm": len(apps)},
                    to_state={"home_qm": new_qm_id, "apps_on_qm": 1},
                )

        self.log.record(
            stage="constraint_enforcement",
            action="split_summary",
            subject_type="model",
            subject_id="all_nodes",
            description=(
                f"Split {len(shared_qms)} shared QMs. "
                f"Primary apps keep original QMs; others get new dedicated QMs."
            ),
            reason="1-app-per-QM enforcement complete",
            evidence={
                "shared_qms_found": len(shared_qms),
                "new_qms_created": sum(len(apps) - 1 for apps in shared_qms.values()),
                "total_nodes": len(model.nodes),
            },
        )

        return model
