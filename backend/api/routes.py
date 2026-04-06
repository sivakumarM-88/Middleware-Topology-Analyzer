"""REST API endpoints for TopologyIQ."""

from __future__ import annotations

import io
import json
import os
import tempfile
import traceback
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents.chat_agent import ChatAgent
from engine.adapter import MQAdapter
from engine.decision_log import DecisionLog
from engine.discovery import GraphDiscovery
from engine.model import ClientRole, PortDirection, TopologyModel
from engine.naming import NamingEngine
from engine.onboarding import OnboardingEngine
from engine.optimizer import OptimizationPipeline, OptimizationResult
from engine.scorer import ComplexityScorer

router = APIRouter()

# ── In-memory state ──────────────────────────────────────────────────────────
_state: Dict[str, Any] = {
    "as_is_model": None,
    "target_model": None,
    "optimization_result": None,
    "decision_log": None,
    "adapter": None,
}
_scorer = ComplexityScorer()
_chat_agent = ChatAgent()


# ── Pydantic schemas ────────────────────────────────────────────────────────
class OnboardRequest(BaseModel):
    app_id: str
    app_name: str
    role: str = "producer"  # producer | consumer | both
    target_app_id: str
    neighborhood: str = ""
    pci: bool = False
    trtc: str = ""


class OnboardApplyRequest(BaseModel):
    app_id: str
    option_index: int = 0


class ChatRequest(BaseModel):
    message: str
    use_llm: bool = False


# ── Helpers ──────────────────────────────────────────────────────────────────
def _client_detail(client, model) -> dict:
    """Build rich per-client data including queue breakdown and remote targets."""
    ports = [model.ports[pid] for pid in client.connected_ports if pid in model.ports]
    local_q = [p for p in ports if p.direction == PortDirection.LOCAL]
    remote_q = [p for p in ports if p.direction == PortDirection.REMOTE]
    alias_q = [p for p in ports if p.direction == PortDirection.ALIAS]
    xmit_q = [p for p in ports if p.direction == PortDirection.TRANSMISSION]
    # Remote targets: QMs this app communicates with (from remote + alias queues)
    remote_targets = sorted(set(
        p.remote_node_id for p in ports
        if p.direction in (PortDirection.REMOTE, PortDirection.ALIAS)
        and p.remote_node_id
        and p.remote_node_id != client.home_node_id  # exclude self-references
    ))
    # All QMs where this app has ports (includes home + any other QMs with local queues)
    all_node_ids = sorted(set(
        p.node_id for p in ports if p.node_id
    ))
    return {
        "id": client.id,
        "app_id": client.app_id,
        "name": client.app_name,
        "role": client.role.value,
        "home_node_id": client.home_node_id,
        "all_node_ids": all_node_ids,
        "local_queue_count": len(local_q),
        "remote_queue_count": len(remote_q),
        "alias_queue_count": len(alias_q),
        "xmit_queue_count": len(xmit_q),
        "remote_targets": remote_targets,
        "queues": [
            {
                "name": p.name,
                "type": p.direction.value,
                "on_qm": p.node_id,
                "remote_qm": p.remote_node_id if p.remote_node_id else None,
                "remote_queue": p.remote_queue if p.remote_queue else None,
                "xmit_queue": p.xmit_queue if p.xmit_queue and p.xmit_queue != "0" else None,
            }
            for p in sorted(ports, key=lambda p: (p.direction.value, p.name))[:40]
        ],
    }


def _model_to_graph_json(model: TopologyModel) -> dict:
    """Convert a TopologyModel to D3-compatible nodes+links JSON.

    Uses pre-built lookup maps to avoid O(N²) nested scans.
    """
    # Build lookup maps ONCE: O(N)
    node_clients: Dict[str, List] = {nid: [] for nid in model.nodes}
    for c in model.clients.values():
        if c.home_node_id in node_clients:
            node_clients[c.home_node_id].append(c)

    node_ports: Dict[str, List] = {nid: [] for nid in model.nodes}
    for p in model.ports.values():
        if p.node_id in node_ports:
            node_ports[p.node_id].append(p)

    # Pre-compute edge flows: (source, target) → [app_ids]
    edge_flows: Dict[tuple, List[str]] = {}
    for c in model.clients.values():
        for pid in c.connected_ports:
            port = model.ports.get(pid)
            if port and port.direction == PortDirection.REMOTE and port.remote_node_id:
                key = (c.home_node_id, port.remote_node_id)
                edge_flows.setdefault(key, []).append(f"{c.app_id} -> {port.remote_node_id}")

    # Pre-compute which nodes have edges (for isolated detection)
    edge_nodes: set = set()
    for e in model.edges.values():
        edge_nodes.add(e.source_node_id)
        edge_nodes.add(e.target_node_id)

    nodes = []
    for n in model.nodes.values():
        clients_on = node_clients.get(n.id, [])
        ports_on = node_ports.get(n.id, [])
        local_q = sum(1 for p in ports_on if p.direction == PortDirection.LOCAL)
        remote_q = sum(1 for p in ports_on if p.direction == PortDirection.REMOTE)
        alias_q = sum(1 for p in ports_on if p.direction == PortDirection.ALIAS)
        is_isolated = n.id not in edge_nodes

        nodes.append({
            "id": n.id,
            "name": n.name,
            "type": n.node_type.value,
            "region": n.region,
            "community_id": n.community_id,
            "is_hub": n.is_hub,
            "is_isolated": is_isolated,
            "client_count": len(clients_on),
            "clients": [
                _client_detail(c, model)
                for c in clients_on
            ],
            "port_count": len(ports_on),
            "local_queues": local_q,
            "remote_queues": remote_q,
            "alias_queues": alias_q,
            **n.business_metadata,
        })

    links = []
    for e in model.edges.values():
        flows = edge_flows.get((e.source_node_id, e.target_node_id), [])
        links.append({
            "id": e.id,
            "source": e.source_node_id,
            "target": e.target_node_id,
            "name": e.name,
            "type": e.edge_type.value,
            "topology": e.metadata.get("topology", "direct"),
            "flows": flows,
            **{k: v for k, v in e.metadata.items() if k != "topology"},
        })

    return {
        "nodes": nodes,
        "links": links,
        "summary": {
            "total_nodes": len(nodes),
            "total_edges": len(links),
            "total_ports": len(model.ports),
            "total_clients": len(model.clients),
            "hubs": [n.id for n in model.nodes.values() if n.is_hub],
            "communities": {
                str(cid): members
                for cid, members in model.get_communities().items()
            },
        },
    }


def _get_role(s: str) -> ClientRole:
    s = s.strip().lower()
    if s == "producer":
        return ClientRole.PRODUCER
    if s == "consumer":
        return ClientRole.CONSUMER
    return ClientRole.BOTH


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_csv(file: UploadFile = File(...)):
    """Upload a CSV file and parse into topology model."""
    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "File must be a CSV")

    tmp_path = None
    try:
        contents = await file.read()
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
        tmp.write(contents)
        tmp.close()
        tmp_path = tmp.name

        log = DecisionLog()
        adapter = MQAdapter(decision_log=log)
        model = adapter.parse(tmp_path)

        # Run graph discovery immediately so as-is view shows inferred channels
        discovery = GraphDiscovery(log)
        model = discovery.run(model)

        _state["as_is_model"] = model
        _state["target_model"] = None
        _state["optimization_result"] = None
        _state["decision_log"] = log
        _state["adapter"] = adapter

        metrics = _scorer.score(model)

        return {
            "status": "ok",
            "summary": model.summary(),
            "metrics": metrics.to_dict(),
            "nodes": list(model.nodes.keys()),
            "clients": [
                {"id": c.id, "app_id": c.app_id, "name": c.app_name,
                 "role": c.role.value, "home_qm": c.home_node_id}
                for c in model.clients.values()
            ],
            "parsing_decisions": len(log),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to parse CSV: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@router.post("/optimize")
async def run_optimization():
    """Run the full optimization pipeline."""
    model = _state.get("as_is_model")
    if model is None:
        raise HTTPException(400, "No topology loaded. Upload a CSV first.")

    try:
        pipeline = OptimizationPipeline(_scorer)
        result = pipeline.run(model.deep_copy())

        _state["target_model"] = result.target_model
        _state["optimization_result"] = result
        _state["decision_log"] = result.decision_log

        return {
            "status": "ok",
            **result.to_dict(),
        }
    except Exception as e:
        raise HTTPException(500, f"Optimization failed: {e}")


@router.get("/topology/as-is")
async def get_as_is_topology():
    """Get the as-is topology graph data for D3 visualization."""
    model = _state.get("as_is_model")
    if model is None:
        raise HTTPException(400, "No topology loaded.")
    return _model_to_graph_json(model)


@router.get("/topology/target")
async def get_target_topology():
    """Get the target topology graph data for D3 visualization."""
    model = _state.get("target_model")
    if model is None:
        raise HTTPException(400, "No target topology. Run optimization first.")
    return _model_to_graph_json(model)


@router.get("/metrics")
async def get_metrics():
    """Get complexity metrics for as-is and target topologies."""
    result: OptimizationResult = _state.get("optimization_result")
    if result is None:
        # Return just as-is if available
        model = _state.get("as_is_model")
        if model is None:
            raise HTTPException(400, "No topology loaded.")
        m = _scorer.score(model)
        return {"as_is": m.to_dict(), "target": None, "reduction_pct": None, "stages": []}

    return {
        "as_is": result.as_is_metrics.to_dict(),
        "target": result.target_metrics.to_dict(),
        "reduction_pct": result.complexity_reduction_pct,
        "stages": [s.to_dict() for s in result.stage_results],
    }


@router.get("/decisions")
async def get_decisions(stage: Optional[str] = None, limit: int = 100, offset: int = 0):
    """Get decision log entries."""
    log: DecisionLog = _state.get("decision_log")
    if log is None:
        return {"decisions": [], "total": 0}

    records = log.records
    if stage:
        records = [r for r in records if r.stage == stage]

    total = len(records)
    records = records[offset : offset + limit]

    return {
        "decisions": [r.to_dict() for r in records],
        "total": total,
    }


@router.post("/onboard")
async def onboard_app(req: OnboardRequest):
    """Generate placement recommendations for a new app."""
    model = _state.get("target_model") or _state.get("as_is_model")
    if model is None:
        raise HTTPException(400, "No topology loaded.")

    engine = OnboardingEngine(scorer=_scorer)
    try:
        result = engine.recommend(
            model,
            app_id=req.app_id,
            app_name=req.app_name,
            role=_get_role(req.role),
            target_app_id=req.target_app_id,
            neighborhood=req.neighborhood,
            pci=req.pci,
            trtc=req.trtc,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    # Stash for apply
    _state["onboard_result"] = result

    return result.to_dict()


@router.post("/onboard/apply")
async def apply_onboard(req: OnboardApplyRequest):
    """Apply a selected onboarding option."""
    result = _state.get("onboard_result")
    if result is None or result.app_id != req.app_id:
        raise HTTPException(400, "No pending onboarding for this app. Call /onboard first.")

    model = _state.get("target_model") or _state.get("as_is_model")
    if model is None:
        raise HTTPException(400, "No topology loaded.")

    engine = OnboardingEngine(scorer=_scorer)
    model = engine.apply(model, result, option_index=req.option_index)

    _state["target_model"] = model
    _state["onboard_result"] = None

    return {
        "status": "ok",
        "summary": model.summary(),
        "metrics": _scorer.score(model).to_dict(),
    }


@router.get("/export/csv")
async def export_csv():
    """Download the target topology as CSV."""
    model = _state.get("target_model")
    adapter = _state.get("adapter")
    if model is None or adapter is None:
        raise HTTPException(400, "No target topology. Run optimization first.")

    df = adapter.export(model)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    buf.seek(0)

    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=target_topology.csv"},
    )


@router.get("/export/mqsc")
async def export_mqsc():
    """Generate MQSC provisioning commands for the target topology."""
    model = _state.get("target_model")
    if model is None:
        raise HTTPException(400, "No target topology. Run optimization first.")

    lines = ["* TopologyIQ - Generated MQSC Commands", "* =" * 30, ""]

    # Group by QM
    for node_id in sorted(model.nodes.keys()):
        lines.append(f"* === Queue Manager: {node_id} ===")
        lines.append("")

        # Local queues
        for port in sorted(model.ports.values(), key=lambda p: p.name):
            if port.node_id != node_id:
                continue
            if port.direction.value == "local":
                persist = "YES" if port.metadata.get("def_persistence") == "Yes" else "NO"
                lines.append(f"DEFINE QLOCAL('{port.name}') DEFPSIST({persist}) REPLACE")

        # Remote queues
        for port in sorted(model.ports.values(), key=lambda p: p.name):
            if port.node_id != node_id:
                continue
            if port.direction.value == "remote":
                lines.append(
                    f"DEFINE QREMOTE('{port.name}') "
                    f"RNAME('{port.remote_queue}') "
                    f"RQMNAME('{port.remote_node_id}') "
                    f"XMITQ('{port.xmit_queue}') REPLACE"
                )

        # Channels (sender)
        for edge in sorted(model.edges.values(), key=lambda e: e.name):
            if edge.source_node_id == node_id:
                lines.append(
                    f"DEFINE CHANNEL('{edge.name}') "
                    f"CHLTYPE(SDR) "
                    f"CONNAME('{edge.target_node_id}(1414)') "
                    f"XMITQ('{NamingEngine.xmit_queue(edge.target_node_id)}') REPLACE"
                )

        # Channels (receiver)
        for edge in sorted(model.edges.values(), key=lambda e: e.name):
            if edge.target_node_id == node_id:
                rcv_name = NamingEngine.channel_receiver(edge.source_node_id, node_id)
                lines.append(
                    f"DEFINE CHANNEL('{rcv_name}') "
                    f"CHLTYPE(RCVR) REPLACE"
                )

        lines.append("")

    content = "\n".join(lines)
    return StreamingResponse(
        io.BytesIO(content.encode()),
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=target_mqsc.txt"},
    )


@router.get("/export/report")
async def export_report():
    """Generate a complexity analysis report."""
    result: OptimizationResult = _state.get("optimization_result")
    if result is None:
        raise HTTPException(400, "No optimization result. Run optimization first.")

    lines = [
        "# TopologyIQ - Complexity Analysis Report",
        "",
        "## Summary",
        f"- As-is complexity score: **{result.as_is_metrics.composite_score:.1f}**",
        f"- Target complexity score: **{result.target_metrics.composite_score:.1f}**",
        f"- Reduction: **{result.complexity_reduction_pct}%**",
        "",
        "## As-Is Topology",
        f"- Queue Managers: {result.as_is_metrics.total_nodes}",
        f"- Channels: {result.as_is_metrics.total_edges}",
        f"- Queues: {result.as_is_metrics.total_ports}",
        f"- Applications: {result.as_is_metrics.total_clients}",
        f"- Density: {result.as_is_metrics.density:.4f}",
        f"- Avg Degree: {result.as_is_metrics.avg_degree:.2f}",
        f"- Max Fan-Out: {result.as_is_metrics.max_fan_out}",
        f"- Cycles: {result.as_is_metrics.cycle_count}",
        "",
        "## Target Topology",
        f"- Queue Managers: {result.target_metrics.total_nodes}",
        f"- Channels: {result.target_metrics.total_edges}",
        f"- Queues: {result.target_metrics.total_ports}",
        f"- Applications: {result.target_metrics.total_clients}",
        f"- Density: {result.target_metrics.density:.4f}",
        f"- Avg Degree: {result.target_metrics.avg_degree:.2f}",
        f"- Max Fan-Out: {result.target_metrics.max_fan_out}",
        f"- Cycles: {result.target_metrics.cycle_count}",
        "",
        "## Stage Waterfall",
    ]

    for sr in result.stage_results:
        lines.append(
            f"- {sr.stage_name}: {sr.metrics_before.composite_score:.1f} → "
            f"{sr.metrics_after.composite_score:.1f} (Δ = {sr.complexity_delta:+.1f})"
        )

    lines.extend([
        "",
        "## Decision Log",
        f"Total decisions: {len(result.decision_log)}",
        "",
    ])

    for r in result.decision_log.records:
        lines.append(f"- **[{r.stage}]** {r.description}")

    content = "\n".join(lines)
    return StreamingResponse(
        io.BytesIO(content.encode()),
        media_type="text/markdown",
        headers={"Content-Disposition": "attachment; filename=complexity_report.md"},
    )


@router.post("/chat")
async def chat(req: ChatRequest):
    """AI-powered chat endpoint with full topology awareness."""
    model = _state.get("target_model") or _state.get("as_is_model")
    log: DecisionLog = _state.get("decision_log")

    if model is None:
        return {"response": "No topology loaded yet. Please upload a CSV file first."}

    metrics = _scorer.score(model)
    opt_result = _state.get("optimization_result")

    response = _chat_agent.chat(
        message=req.message,
        model=model,
        metrics=metrics,
        decision_log=log,
        optimization_result=opt_result,
        use_llm=req.use_llm,
    )

    return {"response": response}


@router.post("/chat/reset")
async def chat_reset():
    """Reset chat history."""
    _chat_agent.reset()
    return {"status": "ok"}
