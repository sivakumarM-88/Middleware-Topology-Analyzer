"""Conversational agent for topology Q&A powered by Ollama / Claude API."""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from engine.decision_log import DecisionLog
from engine.model import PortDirection, TopologyModel
from engine.scorer import ComplexityMetrics, ComplexityScorer

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3-coder:latest")


def _build_topology_context(
    model: TopologyModel,
    metrics: ComplexityMetrics,
    decision_log: Optional[DecisionLog] = None,
    optimization_result: Any = None,
) -> str:
    """Serialize the full topology state for the system prompt."""

    # Nodes
    node_lines = []
    for n in model.nodes.values():
        clients = [c for c in model.clients.values() if c.home_node_id == n.id]
        ports = [p for p in model.ports.values() if p.node_id == n.id]
        local_q = sum(1 for p in ports if p.direction == PortDirection.LOCAL)
        remote_q = sum(1 for p in ports if p.direction == PortDirection.REMOTE)
        alias_q = sum(1 for p in ports if p.direction == PortDirection.ALIAS)
        app_list = ", ".join(f"{c.app_id}({c.app_name}, {c.role.value})" for c in clients)
        hub_tag = " [HUB]" if n.is_hub else ""
        comm_tag = f" community={n.community_id}" if n.community_id is not None else ""
        node_lines.append(
            f"  - {n.id}{hub_tag}{comm_tag} | region={n.region} | "
            f"queues: {len(ports)} (L:{local_q} R:{remote_q} A:{alias_q}) | "
            f"apps: [{app_list}] | "
            f"biz: PCI_apps={n.business_metadata.get('pci_apps_count', 0)}, "
            f"critical_payment={n.business_metadata.get('critical_payment_apps_count', 0)}, "
            f"trtc={n.business_metadata.get('trtc_classes', [])}"
        )

    # Edges
    edge_lines = []
    for e in model.edges.values():
        topo = e.metadata.get("topology", "direct")
        edge_lines.append(f"  - {e.name}: {e.source_node_id} -> {e.target_node_id} ({topo})")

    # Clients
    client_lines = []
    for c in model.clients.values():
        port_count = len(c.connected_ports)
        client_lines.append(
            f"  - {c.app_id} ({c.app_name}) | role={c.role.value} | home_qm={c.home_node_id} | "
            f"ports={port_count} | pci={c.business_metadata.get('pci', False)} | "
            f"neighborhood={c.business_metadata.get('neighborhood', '')} | "
            f"trtc={c.business_metadata.get('trtc', '')}"
        )

    # Orphans
    client_nodes = {c.home_node_id for c in model.clients.values()}
    edge_nodes = set()
    for e in model.edges.values():
        edge_nodes.add(e.source_node_id)
        edge_nodes.add(e.target_node_id)
    orphan_nodes = [nid for nid in model.nodes if nid not in client_nodes and nid not in edge_nodes]

    client_ports = set()
    for c in model.clients.values():
        client_ports.update(c.connected_ports)
    orphan_ports = [pid for pid in model.ports if pid not in client_ports]

    # Ports detail
    port_lines = []
    for p in model.ports.values():
        remote_info = ""
        if p.remote_node_id:
            remote_info = f" -> remote_qm={p.remote_node_id}, remote_q={p.remote_queue}, xmit={p.xmit_queue}"
        port_lines.append(f"  - {p.id}: type={p.direction.value}{remote_info}")

    # Communities
    communities = model.get_communities()
    comm_lines = []
    for cid, members in sorted(communities.items()):
        hub = next((m for m in members if model.nodes[m].is_hub), None)
        comm_lines.append(f"  - Community {cid}: members=[{', '.join(members)}], hub={hub or 'none'}")

    # Decision log
    decision_lines = []
    if decision_log:
        for r in decision_log.last_n(30):
            decision_lines.append(
                f"  - [{r.stage}] {r.action}: {r.description} | reason: {r.reason}"
            )

    # Optimization summary
    opt_summary = ""
    if optimization_result:
        opt_summary = (
            f"\nOPTIMIZATION RESULT:\n"
            f"  As-is score: {optimization_result.as_is_metrics.composite_score:.1f}\n"
            f"  Target score: {optimization_result.target_metrics.composite_score:.1f}\n"
            f"  Reduction: {optimization_result.complexity_reduction_pct}%\n"
            f"  Stages:\n"
        )
        for sr in optimization_result.stage_results:
            opt_summary += (
                f"    - {sr.stage_name}: {sr.metrics_before.composite_score:.1f} -> "
                f"{sr.metrics_after.composite_score:.1f} (delta={sr.complexity_delta:+.1f})\n"
            )

    return f"""CURRENT TOPOLOGY STATE:

QUEUE MANAGERS ({len(model.nodes)}):
{chr(10).join(node_lines)}

CHANNELS ({len(model.edges)}):
{chr(10).join(edge_lines)}

APPLICATIONS ({len(model.clients)}):
{chr(10).join(client_lines)}

COMMUNITIES ({len(communities)}):
{chr(10).join(comm_lines)}

QUEUES/PORTS ({len(model.ports)}):
{chr(10).join(port_lines[:50])}
{"  ... and " + str(len(port_lines) - 50) + " more" if len(port_lines) > 50 else ""}

ORPHAN ANALYSIS:
  Orphan nodes (no clients, no channels): {orphan_nodes if orphan_nodes else "none"}
  Orphan ports (no client reference): {len(orphan_ports)} ports
  Orphan port IDs: {orphan_ports[:20] if orphan_ports else "none"}

COMPLEXITY METRICS:
  Composite score: {metrics.composite_score:.1f}
  Nodes: {metrics.total_nodes}, Edges: {metrics.total_edges}, Ports: {metrics.total_ports}, Clients: {metrics.total_clients}
  Avg degree: {metrics.avg_degree:.2f}, Max fan-out: {metrics.max_fan_out}, Max fan-in: {metrics.max_fan_in}
  Avg path length: {metrics.avg_path_length:.2f}, Max path length: {metrics.max_path_length}
  Cycles: {metrics.cycle_count}, Density: {metrics.density:.4f}
  Orphan nodes: {metrics.orphan_nodes}, Orphan ports: {metrics.orphan_ports}
  Communities: {metrics.communities}, Cross-community edges: {metrics.cross_community_edges}
{opt_summary}
DECISION LOG (last 30):
{chr(10).join(decision_lines) if decision_lines else "  No decisions recorded yet."}
"""


SYSTEM_PROMPT = """You are the TopologyIQ conversational agent — an expert in IBM MQ topology analysis and optimization.

You have full access to the current topology state shown below. Answer questions accurately using this data.

You can:
1. QUERY — Answer questions about the topology: counts, locations, relationships, properties
2. WHAT-IF — Evaluate hypothetical changes: "What if we retire QM X?", "What if we merge communities?"
3. EXPLAIN — Explain optimization decisions with evidence from the decision log
4. ANALYZE — Identify orphan objects, bottlenecks, high fan-out, cycles, anomalies
5. GENERATE — Describe MQSC commands, configuration changes, migration plans

Rules:
- Always cite specific data from the topology state. Use exact QM names, app IDs, queue names.
- When discussing orphans, check both orphan nodes (no clients AND no channels) and orphan ports (no client reference).
- For complexity questions, explain the scoring formula components.
- Use markdown formatting for readability.
- Be concise but thorough. Give the direct answer first, then supporting detail.
- If the user asks about something not in the data, say so clearly.

{topology_context}
"""


class ChatAgent:
    """Topology chat agent using Ollama (local) or Claude API."""

    def __init__(self):
        self._history: List[Dict[str, str]] = []
        self._ollama_available: Optional[bool] = None

    def reset(self):
        self._history = []

    def _check_ollama(self) -> bool:
        """Check if Ollama is reachable."""
        if self._ollama_available is not None:
            return self._ollama_available
        try:
            req = urllib.request.Request(f"{OLLAMA_URL}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                self._ollama_available = resp.status == 200
        except Exception:
            self._ollama_available = False
        return self._ollama_available

    def chat(
        self,
        message: str,
        model: TopologyModel,
        metrics: ComplexityMetrics,
        decision_log: Optional[DecisionLog] = None,
        optimization_result: Any = None,
    ) -> str:
        """Send a message and get a response.

        Strategy: Try the precise local handler first for structured queries
        (orphans, counts, where, why, etc.) — these give exact data-driven answers.
        If no local pattern matches (returns None), use Ollama/Claude for
        open-ended reasoning.
        """
        # Step 1: Try precise local analysis for structured queries
        local_result = self._chat_local(
            message, model, metrics, decision_log, optimization_result
        )
        if local_result is not None:
            return local_result

        # Step 2: For open-ended questions, use LLM
        topology_context = _build_topology_context(
            model, metrics, decision_log, optimization_result
        )

        # Try Ollama (local LLM)
        if self._check_ollama():
            try:
                return self._chat_ollama(message, topology_context)
            except Exception as e:
                print(f"[ChatAgent] Ollama error: {e}, falling back...")

        # Try Claude API
        try:
            import anthropic
            client = anthropic.Anthropic()
            return self._chat_claude(client, message, topology_context)
        except Exception:
            pass

        # Final fallback: generic help message
        return self._fallback_help(model, metrics)

    def _chat_ollama(self, message: str, topology_context: str) -> str:
        """Chat via Ollama REST API."""
        system = SYSTEM_PROMPT.format(topology_context=topology_context)

        self._history.append({"role": "user", "content": message})

        # Build messages with system prompt
        messages = [{"role": "system", "content": system}]
        messages.extend(self._history[-16:])  # Keep recent history

        payload = json.dumps({
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.3,
                "num_predict": 2048,
            },
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        reply = data.get("message", {}).get("content", "")
        if not reply:
            raise ValueError("Empty response from Ollama")

        # Strip thinking tags if model uses them (qwen3 does /think)
        import re
        reply = re.sub(r'<think>.*?</think>', '', reply, flags=re.DOTALL).strip()

        self._history.append({"role": "assistant", "content": reply})
        return reply

    def _chat_claude(self, client, message: str, topology_context: str) -> str:
        system = SYSTEM_PROMPT.format(topology_context=topology_context)

        self._history.append({"role": "user", "content": message})
        messages = self._history[-16:]

        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2048,
                system=system,
                messages=messages,
            )
            reply = response.content[0].text
            self._history.append({"role": "assistant", "content": reply})
            return reply
        except Exception as e:
            self._history.pop()
            raise

    def _chat_local(
        self,
        message: str,
        model: TopologyModel,
        metrics: ComplexityMetrics,
        decision_log: Optional[DecisionLog] = None,
        optimization_result: Any = None,
    ) -> Optional[str]:
        """Precise data-driven answers for structured queries.

        Returns None if no pattern matched — caller should use LLM instead.
        """
        msg = message.lower().strip()

        # --- ORPHAN ANALYSIS ---
        if "orphan" in msg:
            return self._analyze_orphans(model, metrics, msg)

        # --- COUNTS / LIST / SHOW ---
        if any(w in msg for w in ["how many", "count", "total", "list", "show", "all", "tell me about"]):
            if "qm" in msg or "queue manager" in msg or "node" in msg:
                lines = [f"**{len(model.nodes)} Queue Managers:**"]
                for n in model.nodes.values():
                    clients = [c for c in model.clients.values() if c.home_node_id == n.id]
                    ports = [p for p in model.ports.values() if p.node_id == n.id]
                    hub = " [HUB]" if n.is_hub else ""
                    comm = f" (C{n.community_id})" if n.community_id is not None else ""
                    lines.append(f"- **{n.id}**{hub}{comm}: {len(clients)} apps, {len(ports)} queues, region={n.region}")
                return "\n".join(lines)

            if "channel" in msg or "edge" in msg:
                lines = [f"**{len(model.edges)} Channels:**"]
                for e in model.edges.values():
                    topo = e.metadata.get("topology", "direct")
                    lines.append(f"- `{e.name}`: {e.source_node_id} → {e.target_node_id} ({topo})")
                return "\n".join(lines)

            if "app" in msg or "client" in msg:
                lines = [f"**{len(model.clients)} Applications:**"]
                for c in model.clients.values():
                    lines.append(
                        f"- **{c.app_id}** ({c.app_name}): {c.role.value} on QM {c.home_node_id}, "
                        f"PCI={c.business_metadata.get('pci', False)}, "
                        f"neighborhood={c.business_metadata.get('neighborhood', '—')}"
                    )
                return "\n".join(lines)

            if "queue" in msg or "port" in msg:
                lines = [f"**{len(model.ports)} Queues across all QMs:**"]
                for nid in sorted(model.nodes.keys()):
                    ports = [p for p in model.ports.values() if p.node_id == nid]
                    local_q = sum(1 for p in ports if p.direction == PortDirection.LOCAL)
                    remote_q = sum(1 for p in ports if p.direction == PortDirection.REMOTE)
                    alias_q = sum(1 for p in ports if p.direction == PortDirection.ALIAS)
                    lines.append(f"\n**{nid}** ({len(ports)} queues: {local_q}L, {remote_q}R, {alias_q}A):")
                    for p in ports:
                        remote_info = f" → {p.remote_node_id}" if p.remote_node_id else ""
                        lines.append(f"  - `{p.name}` [{p.direction.value}]{remote_info}")
                return "\n".join(lines)

            if "communit" in msg:
                return self._describe_communities(model)

            if "decision" in msg or "log" in msg:
                return self._describe_decisions(decision_log)

        # --- WHY / EXPLAIN (check before simpler keyword matches) ---
        if "why" in msg or "explain" in msg:
            return self._explain(msg, decision_log)

        # --- WHERE / FIND ---
        if any(w in msg for w in ["where", "find", "which qm", "locate"]):
            for c in model.clients.values():
                if c.app_id.lower() in msg or c.app_name.lower() in msg:
                    ports = [model.ports[pid] for pid in c.connected_ports if pid in model.ports]
                    port_summary = ", ".join(f"`{p.name}` ({p.direction.value})" for p in ports[:5])
                    return (
                        f"**{c.app_name}** (`{c.app_id}`) lives on queue manager **{c.home_node_id}**\n\n"
                        f"- Role: {c.role.value}\n"
                        f"- Connected queues ({len(ports)}): {port_summary}\n"
                        f"- PCI: {c.business_metadata.get('pci', False)}\n"
                        f"- Neighborhood: {c.business_metadata.get('neighborhood', '—')}\n"
                        f"- TRTC: {c.business_metadata.get('trtc', '—')}"
                    )

        # --- HUB ---
        if "hub" in msg:
            hubs = model.get_hubs()
            if not hubs:
                return "No hubs elected yet. Run the optimizer first to detect communities and elect hubs."
            lines = ["**Hub Queue Managers:**"]
            for h in hubs:
                node = model.nodes[h]
                clients = [c for c in model.clients.values() if c.home_node_id == h]
                edges = [e for e in model.edges.values() if e.source_node_id == h or e.target_node_id == h]
                lines.append(
                    f"- **{h}** (Community {node.community_id}): "
                    f"{len(clients)} apps, {len(edges)} channels, "
                    f"PCI_apps={node.business_metadata.get('pci_apps_count', 0)}, "
                    f"critical_payment={node.business_metadata.get('critical_payment_apps_count', 0)}"
                )
            return "\n".join(lines)

        # --- COMMUNITY ---
        if "communit" in msg:
            return self._describe_communities(model)

        # --- COMPLEXITY ---
        if "complexit" in msg or "score" in msg or "metric" in msg:
            lines = [f"**Complexity Metrics:**\n"]
            lines.append(f"| Metric | Value |")
            lines.append(f"|--------|-------|")
            lines.append(f"| Composite Score | **{metrics.composite_score:.1f}** |")
            lines.append(f"| Nodes | {metrics.total_nodes} |")
            lines.append(f"| Edges | {metrics.total_edges} |")
            lines.append(f"| Ports | {metrics.total_ports} |")
            lines.append(f"| Clients | {metrics.total_clients} |")
            lines.append(f"| Avg Degree | {metrics.avg_degree:.2f} |")
            lines.append(f"| Max Fan-Out | {metrics.max_fan_out} |")
            lines.append(f"| Max Fan-In | {metrics.max_fan_in} |")
            lines.append(f"| Avg Path Length | {metrics.avg_path_length:.2f} |")
            lines.append(f"| Cycles | {metrics.cycle_count} |")
            lines.append(f"| Density | {metrics.density:.4f} |")
            lines.append(f"| Orphan Nodes | {metrics.orphan_nodes} |")
            lines.append(f"| Orphan Ports | {metrics.orphan_ports} |")
            lines.append(f"| Cross-Community Edges | {metrics.cross_community_edges} |")

            if optimization_result:
                lines.append(f"\n**Optimization:**")
                lines.append(f"- As-is: {optimization_result.as_is_metrics.composite_score:.1f}")
                lines.append(f"- Target: {optimization_result.target_metrics.composite_score:.1f}")
                lines.append(f"- Reduction: **{optimization_result.complexity_reduction_pct}%**")
            return "\n".join(lines)

        # --- DECISIONS ---
        if "decision" in msg or "log" in msg:
            return self._describe_decisions(decision_log)

        # --- WHAT-IF ---
        if "what if" in msg or "what-if" in msg:
            return (
                "What-if analysis requires specifying a change. Try:\n"
                "- \"What if we retire QM WL6EX9Z?\"\n"
                "- \"What if we remove app LGBY?\"\n"
                "- \"What if we merge community 0 and 1?\"\n\n"
                "I'll compute the impact on complexity, affected apps, and required migrations."
            )

        # --- QM-specific queries ---
        for nid in model.nodes:
            if nid.lower() in msg:
                return self._describe_node(model, nid, metrics)

        # --- App-specific queries ---
        for c in model.clients.values():
            if c.app_id.lower() in msg:
                return self._describe_client(model, c)

        # No pattern matched — return None to let LLM handle it
        return None

    def _fallback_help(self, model: TopologyModel, metrics: ComplexityMetrics) -> str:
        """Generic help message when no LLM is available."""
        summary = model.summary()
        hubs = model.get_hubs()
        communities = model.get_communities()
        return (
            f"**Current Topology State:**\n"
            f"- {summary['nodes']} queue managers, {summary['edges']} channels, "
            f"{summary['clients']} apps, {summary['ports']} queues\n"
            f"- Complexity score: {metrics.composite_score:.1f}\n"
            f"- Communities: {len(communities)}\n"
            f"- Hubs: {', '.join(hubs) if hubs else 'none (run optimizer)'}\n\n"
            f"I can answer questions about:\n"
            f"- **Nodes**: any QM name (e.g., \"{list(model.nodes.keys())[0]}\")\n"
            f"- **Apps**: any app ID (e.g., \"{list(model.clients.values())[0].app_id if model.clients else 'X'}\")\n"
            f"- **Analysis**: orphans, complexity, communities, hubs, channels\n"
            f"- **Decisions**: why certain optimizations were made\n"
            f"- **Counts**: \"list all queues\", \"how many channels\"\n\n"
            f"Try being specific: \"list orphan nodes\", \"show channels for WQ26\", \"why was WQ39 elected hub?\""
        )

    def _chat_local_simple(self, message: str) -> str:
        """Minimal fallback when we have no model context."""
        return "I couldn't process that with the Claude API. Please try rephrasing your question."

    def _analyze_orphans(self, model: TopologyModel, metrics: ComplexityMetrics, msg: str) -> str:
        client_nodes = {c.home_node_id for c in model.clients.values()}
        edge_nodes = set()
        for e in model.edges.values():
            edge_nodes.add(e.source_node_id)
            edge_nodes.add(e.target_node_id)

        # Fully orphan: no clients AND no channels
        orphan_nodes = [nid for nid in model.nodes if nid not in client_nodes and nid not in edge_nodes]

        # Isolated: have apps but ZERO channels (no connectivity to other QMs)
        isolated_nodes = [
            nid for nid in model.nodes
            if nid in client_nodes and nid not in edge_nodes
        ]

        # Routing-only: have channels but no apps
        routing_only_nodes = [nid for nid in model.nodes if nid not in client_nodes and nid in edge_nodes]

        # Orphan ports
        client_ports = set()
        for c in model.clients.values():
            client_ports.update(c.connected_ports)
        orphan_ports = [pid for pid in model.ports if pid not in client_ports]

        lines = ["**Orphan & Isolation Analysis:**\n"]

        # 1. Fully orphan
        lines.append(f"**Fully Orphan Nodes** (no clients, no channels): **{len(orphan_nodes)}**")
        if orphan_nodes:
            for nid in orphan_nodes:
                n = model.nodes[nid]
                ports = [p for p in model.ports.values() if p.node_id == nid]
                lines.append(f"- `{nid}`: {len(ports)} queues, region={n.region} — **candidate for removal**")
        else:
            lines.append("- None found.")

        # 2. Isolated (THIS IS THE KEY FIX - WL6EX9Z will show here)
        lines.append(f"\n**Isolated Nodes** (have apps but ZERO channels — no connectivity): **{len(isolated_nodes)}**")
        if isolated_nodes:
            for nid in isolated_nodes:
                n = model.nodes[nid]
                clients = [c for c in model.clients.values() if c.home_node_id == nid]
                ports = [p for p in model.ports.values() if p.node_id == nid]
                app_names = ", ".join(f"{c.app_id}({c.app_name})" for c in clients)
                lines.append(
                    f"- `{nid}`: {len(clients)} apps [{app_names}], {len(ports)} queues, "
                    f"region={n.region} — **island node, no message flow to other QMs**"
                )
        else:
            lines.append("- None found. All nodes with apps have at least one channel.")

        # 3. Routing-only
        lines.append(f"\n**Routing-Only Nodes** (channels but no apps): **{len(routing_only_nodes)}**")
        if routing_only_nodes:
            for nid in routing_only_nodes:
                edges = [e for e in model.edges.values() if e.source_node_id == nid or e.target_node_id == nid]
                lines.append(f"- `{nid}`: {len(edges)} channels — pass-through routing only")
        else:
            lines.append("- None found.")

        # 4. Orphan ports
        lines.append(f"\n**Orphan Ports** (queues not referenced by any app): **{len(orphan_ports)}**")
        if orphan_ports:
            for pid in orphan_ports[:15]:
                port = model.ports[pid]
                lines.append(f"- `{pid}` [{port.direction.value}] on {port.node_id}")
            if len(orphan_ports) > 15:
                lines.append(f"- ...and {len(orphan_ports) - 15} more")
        else:
            lines.append("- None found.")

        return "\n".join(lines)

    def _describe_communities(self, model: TopologyModel) -> str:
        communities = model.get_communities()
        if not communities:
            return "No communities detected yet. Run the optimizer to perform Louvain community detection."

        lines = [f"**{len(communities)} Communities Detected:**\n"]
        for cid, members in sorted(communities.items()):
            hub = next((m for m in members if model.nodes[m].is_hub), None)
            lines.append(f"**Community {cid}** ({len(members)} members):")
            for m in members:
                node = model.nodes[m]
                clients = [c for c in model.clients.values() if c.home_node_id == m]
                hub_tag = " **[HUB]**" if node.is_hub else ""
                lines.append(f"  - `{m}`{hub_tag}: {len(clients)} apps, region={node.region}")
            # Intra-community edges
            intra = [
                e for e in model.edges.values()
                if e.source_node_id in members and e.target_node_id in members
            ]
            lines.append(f"  - Internal channels: {len(intra)}")
        return "\n".join(lines)

    def _describe_decisions(self, decision_log: Optional[DecisionLog]) -> str:
        if not decision_log or len(decision_log) == 0:
            return "No decisions recorded yet. Run the optimizer to generate decisions."

        lines = [f"**{len(decision_log)} Decisions Recorded:**\n"]
        # Group by stage
        by_stage: Dict[str, list] = {}
        for r in decision_log.records:
            by_stage.setdefault(r.stage, []).append(r)

        for stage, records in by_stage.items():
            lines.append(f"**{stage}** ({len(records)} decisions):")
            for r in records[:5]:
                delta = f" (Δ={r.complexity_delta:+.1f})" if r.complexity_delta else ""
                lines.append(f"  - {r.action}: {r.description}{delta}")
            if len(records) > 5:
                lines.append(f"  - ...and {len(records) - 5} more")
        return "\n".join(lines)

    def _explain(self, msg: str, decision_log: Optional[DecisionLog]) -> str:
        if not decision_log or len(decision_log) == 0:
            return "No decisions to explain yet. Run the optimizer first."

        # Search for relevant decisions
        words = [w for w in msg.split() if len(w) > 2 and w not in ("why", "was", "the", "did", "you", "how", "explain")]
        matches = []
        for r in decision_log.records:
            desc_lower = r.description.lower() + " " + r.subject_id.lower()
            score = sum(1 for w in words if w in desc_lower)
            if score > 0:
                matches.append((score, r))

        matches.sort(key=lambda x: x[0], reverse=True)

        if not matches:
            return (
                "I couldn't find a specific decision matching your question. "
                "Try mentioning a QM name, app ID, or action like 'hub election', 'prune', 'migrate'."
            )

        lines = [f"**Found {min(len(matches), 5)} relevant decisions:**\n"]
        for _, r in matches[:5]:
            lines.append(f"**{r.action}** ({r.stage}):")
            lines.append(f"  {r.description}")
            lines.append(f"  **Reason:** {r.reason}")
            if r.evidence:
                # Format evidence nicely
                evidence_str = json.dumps(r.evidence, indent=2)
                if len(evidence_str) < 500:
                    lines.append(f"  **Evidence:**\n```json\n{evidence_str}\n```")
            if r.complexity_delta:
                lines.append(f"  **Complexity impact:** {r.complexity_delta:+.1f}")
            lines.append("")

        return "\n".join(lines)

    def _describe_node(self, model: TopologyModel, node_id: str, metrics: ComplexityMetrics) -> str:
        node = model.nodes[node_id]
        clients = [c for c in model.clients.values() if c.home_node_id == node_id]
        ports = [p for p in model.ports.values() if p.node_id == node_id]
        edges_out = [e for e in model.edges.values() if e.source_node_id == node_id]
        edges_in = [e for e in model.edges.values() if e.target_node_id == node_id]

        local_q = [p for p in ports if p.direction == PortDirection.LOCAL]
        remote_q = [p for p in ports if p.direction == PortDirection.REMOTE]
        alias_q = [p for p in ports if p.direction == PortDirection.ALIAS]

        lines = [f"**Queue Manager: {node_id}**\n"]
        lines.append(f"| Property | Value |")
        lines.append(f"|----------|-------|")
        lines.append(f"| Region | {node.region} |")
        lines.append(f"| Community | {node.community_id} |")
        lines.append(f"| Hub | {'Yes' if node.is_hub else 'No'} |")
        lines.append(f"| Applications | {len(clients)} |")
        lines.append(f"| Total Queues | {len(ports)} |")
        lines.append(f"| Local Queues | {len(local_q)} |")
        lines.append(f"| Remote Queues | {len(remote_q)} |")
        lines.append(f"| Alias Queues | {len(alias_q)} |")
        lines.append(f"| Outbound Channels | {len(edges_out)} |")
        lines.append(f"| Inbound Channels | {len(edges_in)} |")
        lines.append(f"| PCI Apps | {node.business_metadata.get('pci_apps_count', 0)} |")
        lines.append(f"| Critical Payment | {node.business_metadata.get('critical_payment_apps_count', 0)} |")

        if clients:
            lines.append(f"\n**Applications ({len(clients)}):**")
            for c in clients:
                lines.append(f"- `{c.app_id}` ({c.app_name}) — {c.role.value}")

        if edges_out:
            lines.append(f"\n**Outbound Channels ({len(edges_out)}):**")
            for e in edges_out:
                lines.append(f"- `{e.name}` → {e.target_node_id}")

        if edges_in:
            lines.append(f"\n**Inbound Channels ({len(edges_in)}):**")
            for e in edges_in:
                lines.append(f"- `{e.name}` ← {e.source_node_id}")

        return "\n".join(lines)

    def _describe_client(self, model: TopologyModel, client) -> str:
        ports = [model.ports[pid] for pid in client.connected_ports if pid in model.ports]
        node = model.nodes.get(client.home_node_id)

        lines = [f"**Application: {client.app_name}** (`{client.app_id}`)\n"]
        lines.append(f"| Property | Value |")
        lines.append(f"|----------|-------|")
        lines.append(f"| Home QM | {client.home_node_id} |")
        lines.append(f"| Role | {client.role.value} |")
        lines.append(f"| Connected Queues | {len(ports)} |")
        lines.append(f"| PCI | {client.business_metadata.get('pci', False)} |")
        lines.append(f"| Neighborhood | {client.business_metadata.get('neighborhood', '—')} |")
        lines.append(f"| TRTC | {client.business_metadata.get('trtc', '—')} |")
        lines.append(f"| Community | {node.community_id if node else '—'} |")

        if ports:
            lines.append(f"\n**Connected Queues ({len(ports)}):**")
            for p in ports:
                remote = f" → {p.remote_node_id}" if p.remote_node_id else ""
                lines.append(f"- `{p.name}` [{p.direction.value}]{remote}")

        return "\n".join(lines)
