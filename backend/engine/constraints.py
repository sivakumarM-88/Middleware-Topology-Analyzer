"""Stage 1: Constraint Enforcement - enforce 1-QM-per-app rule."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from .decision_log import DecisionLog
from .model import (
    ClientRole,
    PortDirection,
    TopologyClient,
    TopologyModel,
    TopologyPort,
)
from .naming import NamingEngine


class ConstraintEnforcer:
    """Enforce the 1-QM-per-app constraint by migrating apps to their home QM."""

    def __init__(self, decision_log: DecisionLog):
        self.log = decision_log

    def run(self, model: TopologyModel) -> TopologyModel:
        """Ensure each app_id connects to exactly one queue manager."""
        # Group clients by app_id to find violations
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
            # Elect home QM: the one with the most non-alias connected ports
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

                # Migrate ports from old QM to new QM
                for port_id in list(other.connected_ports):
                    port = model.ports.get(port_id)
                    if port is None:
                        continue

                    if port.direction == PortDirection.ALIAS:
                        # Skip aliases — they're routing references, not connections
                        continue

                    # Create equivalent port on new QM if it doesn't exist
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

                    # Add new port to primary client's connections
                    if new_port_id not in primary.connected_ports:
                        primary.connected_ports.append(new_port_id)

                # Remove the duplicate client
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
            action="enforce_summary",
            subject_type="model",
            subject_id="all_clients",
            description=f"Resolved {len(violations)} app violations, migrated {migrated_count} client entries",
            reason="1-QM-per-app enforcement complete",
            evidence={
                "violations_found": len(violations),
                "migrations": migrated_count,
                "remaining_clients": len(model.clients),
            },
        )

        return model
