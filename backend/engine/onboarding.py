"""Mode 2: New Application Onboarding Engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

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
from .scorer import ComplexityMetrics, ComplexityScorer


@dataclass
class PlacementOption:
    strategy: str  # "same_qm", "same_community", "cross_community"
    qm_id: str
    complexity_delta: float
    objects_needed: List[Dict[str, str]] = field(default_factory=list)
    reasoning: str = ""
    mqsc_commands: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "qm_id": self.qm_id,
            "complexity_delta": round(self.complexity_delta, 2),
            "objects_needed": self.objects_needed,
            "reasoning": self.reasoning,
            "mqsc_commands": self.mqsc_commands,
        }


@dataclass
class OnboardingResult:
    app_id: str
    app_name: str
    target_app_id: str
    options: List[PlacementOption]
    recommended_option: int = 0  # index into options

    def to_dict(self) -> dict:
        return {
            "app_id": self.app_id,
            "app_name": self.app_name,
            "target_app_id": self.target_app_id,
            "options": [o.to_dict() for o in self.options],
            "recommended_option": self.recommended_option,
        }


class OnboardingEngine:
    """Place a new application into the optimized topology."""

    def __init__(
        self,
        decision_log: Optional[DecisionLog] = None,
        scorer: Optional[ComplexityScorer] = None,
    ):
        self.log = decision_log or DecisionLog()
        self.scorer = scorer or ComplexityScorer()

    def recommend(
        self,
        model: TopologyModel,
        app_id: str,
        app_name: str,
        role: ClientRole,
        target_app_id: str,
        neighborhood: str = "",
        pci: bool = False,
        trtc: str = "",
    ) -> OnboardingResult:
        """Generate placement options ranked by complexity delta."""
        # Find target app's QM
        target_client = None
        for client in model.clients.values():
            if client.app_id == target_app_id:
                target_client = client
                break

        if not target_client:
            raise ValueError(f"Target app '{target_app_id}' not found in topology")

        target_qm = target_client.home_node_id
        target_node = model.nodes[target_qm]
        target_comm = target_node.community_id

        options: List[PlacementOption] = []

        # Option A: Same QM as target app
        option_a = self._score_same_qm(
            model, app_id, app_name, role, target_client, target_qm, pci, trtc
        )
        options.append(option_a)

        # Option B: Different QM, same community
        if target_comm is not None:
            communities = model.get_communities()
            comm_members = communities.get(target_comm, [])
            for qm_id in comm_members:
                if qm_id == target_qm:
                    continue
                option_b = self._score_same_community(
                    model, app_id, app_name, role, target_client,
                    qm_id, target_qm, pci, trtc
                )
                options.append(option_b)

        # Option C: Different community (if neighborhood mismatch)
        if neighborhood and neighborhood != target_node.region:
            best_qm = self._find_best_qm_in_neighborhood(model, neighborhood, target_comm)
            if best_qm:
                option_c = self._score_cross_community(
                    model, app_id, app_name, role, target_client,
                    best_qm, target_qm, pci, trtc
                )
                options.append(option_c)

        # Sort by complexity delta (lowest first)
        options.sort(key=lambda o: o.complexity_delta)

        result = OnboardingResult(
            app_id=app_id,
            app_name=app_name,
            target_app_id=target_app_id,
            options=options,
            recommended_option=0,
        )

        self.log.record(
            stage="onboarding",
            action="recommend_placement",
            subject_type="client",
            subject_id=app_id,
            description=f"Generated {len(options)} placement options for {app_name}",
            reason=f"Onboarding new app to communicate with {target_app_id}",
            evidence={
                "options_count": len(options),
                "best_strategy": options[0].strategy if options else "none",
                "best_delta": options[0].complexity_delta if options else 0,
            },
        )

        return result

    def apply(
        self,
        model: TopologyModel,
        result: OnboardingResult,
        option_index: int = 0,
    ) -> TopologyModel:
        """Apply a placement option to the topology."""
        option = result.options[option_index]

        # Create the client
        client_id = f"{result.app_id}@{option.qm_id}"
        client = TopologyClient(
            id=client_id,
            app_id=result.app_id,
            app_name=result.app_name,
            home_node_id=option.qm_id,
            role=ClientRole.PRODUCER,  # Will be set properly
            connected_ports=[],
            business_metadata={},
        )

        # Create MQ objects from the option
        for obj in option.objects_needed:
            obj_type = obj.get("type", "")
            name = obj.get("name", "")
            qm = obj.get("qm", option.qm_id)
            port_id = f"{qm}.{name}"

            if obj_type == "local_queue":
                model.ports[port_id] = TopologyPort(
                    id=port_id,
                    node_id=qm,
                    name=name,
                    direction=PortDirection.LOCAL,
                )
                client.connected_ports.append(port_id)

            elif obj_type == "remote_queue":
                model.ports[port_id] = TopologyPort(
                    id=port_id,
                    node_id=qm,
                    name=name,
                    direction=PortDirection.REMOTE,
                    remote_queue=obj.get("remote_queue", ""),
                    remote_node_id=obj.get("remote_qm", ""),
                    xmit_queue=obj.get("xmit_queue", ""),
                )
                client.connected_ports.append(port_id)

            elif obj_type == "channel":
                edge_id = NamingEngine.edge_id(
                    obj.get("from_qm", ""), obj.get("to_qm", "")
                )
                if edge_id not in model.edges:
                    model.edges[edge_id] = TopologyEdge(
                        id=edge_id,
                        source_node_id=obj.get("from_qm", ""),
                        target_node_id=obj.get("to_qm", ""),
                        edge_type=EdgeType.CHANNEL,
                        name=name,
                        metadata={"created_by": "onboarding"},
                    )

        model.clients[client_id] = client

        self.log.record(
            stage="onboarding",
            action="apply_placement",
            subject_type="client",
            subject_id=client_id,
            description=(
                f"Placed {result.app_name} on QM {option.qm_id} "
                f"using {option.strategy} strategy"
            ),
            reason="User accepted placement recommendation",
            evidence={
                "strategy": option.strategy,
                "qm_id": option.qm_id,
                "objects_created": len(option.objects_needed),
                "complexity_delta": option.complexity_delta,
            },
        )

        return model

    def _score_same_qm(
        self, model, app_id, app_name, role, target_client,
        target_qm, pci, trtc,
    ) -> PlacementOption:
        """Score placing the new app on the same QM as the target."""
        trial = model.deep_copy()
        q_name = NamingEngine.queue_name(app_id, target_client.app_id)

        objects = [
            {"type": "local_queue", "name": q_name, "qm": target_qm},
        ]

        # Add the trial client + port
        port_id = f"{target_qm}.{q_name}"
        trial.ports[port_id] = TopologyPort(
            id=port_id, node_id=target_qm, name=q_name,
            direction=PortDirection.LOCAL,
        )
        trial.clients[f"{app_id}@{target_qm}"] = TopologyClient(
            id=f"{app_id}@{target_qm}",
            app_id=app_id, app_name=app_name, home_node_id=target_qm,
            role=role, connected_ports=[port_id],
        )

        before = self.scorer.score(model)
        after = self.scorer.score(trial)
        delta = after.composite_score - before.composite_score

        mqsc = [
            f"DEFINE QLOCAL('{q_name}') REPLACE",
        ]

        return PlacementOption(
            strategy="same_qm",
            qm_id=target_qm,
            complexity_delta=delta,
            objects_needed=objects,
            reasoning=(
                f"Place on same QM as {target_client.app_id} ({target_qm}). "
                f"Simplest option: local queue only, no channels needed."
            ),
            mqsc_commands=mqsc,
        )

    def _score_same_community(
        self, model, app_id, app_name, role, target_client,
        qm_id, target_qm, pci, trtc,
    ) -> PlacementOption:
        """Score placing on a different QM in the same community."""
        trial = model.deep_copy()
        q_name = NamingEngine.queue_name(app_id, target_client.app_id)
        xmit_name = NamingEngine.xmit_queue(target_qm)

        objects = [
            {"type": "remote_queue", "name": q_name, "qm": qm_id,
             "remote_queue": q_name, "remote_qm": target_qm,
             "xmit_queue": xmit_name},
            {"type": "local_queue", "name": q_name, "qm": target_qm},
        ]

        # Check if channel already exists
        edge_id = NamingEngine.edge_id(qm_id, target_qm)
        if edge_id not in trial.edges:
            ch_name = NamingEngine.channel_sender(qm_id, target_qm)
            objects.append({
                "type": "channel", "name": ch_name,
                "from_qm": qm_id, "to_qm": target_qm,
            })
            trial.edges[edge_id] = TopologyEdge(
                id=edge_id, source_node_id=qm_id, target_node_id=target_qm,
                edge_type=EdgeType.CHANNEL, name=ch_name,
            )

        port_id = f"{qm_id}.{q_name}"
        trial.ports[port_id] = TopologyPort(
            id=port_id, node_id=qm_id, name=q_name,
            direction=PortDirection.REMOTE, remote_queue=q_name,
            remote_node_id=target_qm, xmit_queue=xmit_name,
        )
        lq_id = f"{target_qm}.{q_name}"
        trial.ports[lq_id] = TopologyPort(
            id=lq_id, node_id=target_qm, name=q_name,
            direction=PortDirection.LOCAL,
        )
        trial.clients[f"{app_id}@{qm_id}"] = TopologyClient(
            id=f"{app_id}@{qm_id}",
            app_id=app_id, app_name=app_name, home_node_id=qm_id,
            role=role, connected_ports=[port_id],
        )

        before = self.scorer.score(model)
        after = self.scorer.score(trial)
        delta = after.composite_score - before.composite_score

        mqsc = [
            f"* On QM {qm_id}:",
            f"DEFINE QREMOTE('{q_name}') RNAME('{q_name}') RQMNAME('{target_qm}') XMITQ('{xmit_name}') REPLACE",
            f"* On QM {target_qm}:",
            f"DEFINE QLOCAL('{q_name}') REPLACE",
        ]

        return PlacementOption(
            strategy="same_community",
            qm_id=qm_id,
            complexity_delta=delta,
            objects_needed=objects,
            reasoning=(
                f"Place on {qm_id} (same community as {target_qm}). "
                f"Routes via spoke channel to target QM."
            ),
            mqsc_commands=mqsc,
        )

    def _score_cross_community(
        self, model, app_id, app_name, role, target_client,
        qm_id, target_qm, pci, trtc,
    ) -> PlacementOption:
        """Score placing in a different community."""
        trial = model.deep_copy()
        q_name = NamingEngine.queue_name(app_id, target_client.app_id)

        objects = [
            {"type": "remote_queue", "name": q_name, "qm": qm_id,
             "remote_queue": q_name, "remote_qm": target_qm,
             "xmit_queue": NamingEngine.xmit_queue(target_qm)},
            {"type": "local_queue", "name": q_name, "qm": target_qm},
        ]

        # Trial modifications
        port_id = f"{qm_id}.{q_name}"
        trial.ports[port_id] = TopologyPort(
            id=port_id, node_id=qm_id, name=q_name,
            direction=PortDirection.REMOTE, remote_queue=q_name,
            remote_node_id=target_qm,
        )
        lq_id = f"{target_qm}.{q_name}"
        trial.ports[lq_id] = TopologyPort(
            id=lq_id, node_id=target_qm, name=q_name,
            direction=PortDirection.LOCAL,
        )
        trial.clients[f"{app_id}@{qm_id}"] = TopologyClient(
            id=f"{app_id}@{qm_id}",
            app_id=app_id, app_name=app_name, home_node_id=qm_id,
            role=role, connected_ports=[port_id],
        )

        before = self.scorer.score(model)
        after = self.scorer.score(trial)
        delta = after.composite_score - before.composite_score

        mqsc = [
            f"* On QM {qm_id}:",
            f"DEFINE QREMOTE('{q_name}') RNAME('{q_name}') RQMNAME('{target_qm}') REPLACE",
            f"* On QM {target_qm}:",
            f"DEFINE QLOCAL('{q_name}') REPLACE",
        ]

        return PlacementOption(
            strategy="cross_community",
            qm_id=qm_id,
            complexity_delta=delta,
            objects_needed=objects,
            reasoning=(
                f"Place on {qm_id} (different community from {target_qm}). "
                f"Routes cross-community via hub backbone."
            ),
            mqsc_commands=mqsc,
        )

    def _find_best_qm_in_neighborhood(
        self, model: TopologyModel, neighborhood: str,
        exclude_community: Optional[int] = None,
    ) -> Optional[str]:
        """Find the best QM in a given neighborhood, preferring hubs."""
        candidates = []
        for node in model.nodes.values():
            if neighborhood in node.business_metadata.get("neighborhoods", []):
                if exclude_community is None or node.community_id != exclude_community:
                    candidates.append(node)

        if not candidates:
            return None

        # Prefer hubs, then by number of connected clients
        candidates.sort(
            key=lambda n: (n.is_hub, len(model.get_clients_on_node(n.id))),
            reverse=True,
        )
        return candidates[0].id
