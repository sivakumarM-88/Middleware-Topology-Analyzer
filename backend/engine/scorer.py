"""Complexity scoring engine for topology analysis."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

import networkx as nx

if TYPE_CHECKING:
    from .model import TopologyModel


# Default weights
WEIGHTS = {
    "nodes": 1.0,
    "edges": 2.0,
    "avg_degree": 5.0,
    "max_fan_out": 8.0,
    "avg_path_length": 10.0,
    "cycles": 15.0,
    "orphans": 3.0,
    "cross_community": 4.0,
    "density": 20.0,
}

# Scale thresholds — switch to sampled algorithms above these
_SAMPLE_PATH_THRESHOLD = 200   # nodes: sample path lengths instead of all-pairs
_SAMPLE_PATH_COUNT = 100       # number of random source nodes to sample
_CYCLE_LIMIT = 500             # max cycles to enumerate before stopping


@dataclass
class ComplexityMetrics:
    total_nodes: int = 0
    total_edges: int = 0
    total_ports: int = 0
    total_clients: int = 0
    avg_degree: float = 0.0
    max_fan_out: int = 0
    max_fan_in: int = 0
    avg_path_length: float = 0.0
    max_path_length: int = 0
    cycle_count: int = 0
    orphan_nodes: int = 0
    orphan_ports: int = 0
    unused_edges: int = 0
    communities: int = 0
    cross_community_edges: int = 0
    density: float = 0.0
    composite_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "total_ports": self.total_ports,
            "total_clients": self.total_clients,
            "avg_degree": round(self.avg_degree, 3),
            "max_fan_out": self.max_fan_out,
            "max_fan_in": self.max_fan_in,
            "avg_path_length": round(self.avg_path_length, 3),
            "max_path_length": self.max_path_length,
            "cycle_count": self.cycle_count,
            "orphan_nodes": self.orphan_nodes,
            "orphan_ports": self.orphan_ports,
            "unused_edges": self.unused_edges,
            "communities": self.communities,
            "cross_community_edges": self.cross_community_edges,
            "density": round(self.density, 5),
            "composite_score": round(self.composite_score, 2),
        }


class ComplexityScorer:
    """Computes complexity metrics for a TopologyModel."""

    def __init__(self, weights: dict | None = None):
        self.weights = {**WEIGHTS, **(weights or {})}

    def score(self, model: TopologyModel) -> ComplexityMetrics:
        g = model.to_networkx()
        ug = model.get_undirected_graph()
        m = ComplexityMetrics()

        m.total_nodes = len(model.nodes)
        m.total_edges = len(model.edges)
        m.total_ports = len(model.ports)
        m.total_clients = len(model.clients)

        # Degree stats (on undirected graph)
        if ug.number_of_nodes() > 0:
            degrees = [d for _, d in ug.degree()]
            m.avg_degree = sum(degrees) / len(degrees) if degrees else 0.0
        if g.number_of_nodes() > 0:
            out_degrees = [d for _, d in g.out_degree()]
            in_degrees = [d for _, d in g.in_degree()]
            m.max_fan_out = max(out_degrees) if out_degrees else 0
            m.max_fan_in = max(in_degrees) if in_degrees else 0

        # Path lengths — use sampling for large graphs to avoid O(N³)
        self._compute_path_metrics(ug, m)

        # Cycles (directed) — cap enumeration to avoid hanging on dense graphs
        m.cycle_count = self._count_cycles(g)

        # Orphan nodes: QMs with no clients and no channels
        client_nodes = {c.home_node_id for c in model.clients.values()}
        edge_nodes = set()
        for e in model.edges.values():
            edge_nodes.add(e.source_node_id)
            edge_nodes.add(e.target_node_id)
        m.orphan_nodes = sum(
            1 for n in model.nodes
            if n not in client_nodes and n not in edge_nodes
        )

        # Orphan ports: ports with no client referencing them
        client_ports = set()
        for c in model.clients.values():
            client_ports.update(c.connected_ports)
        m.orphan_ports = sum(
            1 for p in model.ports if p not in client_ports
        )

        # Communities
        communities = model.get_communities()
        m.communities = len(communities)

        # Cross-community edges
        node_community = {n.id: n.community_id for n in model.nodes.values()}
        m.cross_community_edges = sum(
            1 for e in model.edges.values()
            if node_community.get(e.source_node_id) is not None
            and node_community.get(e.target_node_id) is not None
            and node_community[e.source_node_id] != node_community[e.target_node_id]
        )

        # Density
        if ug.number_of_nodes() > 1:
            m.density = nx.density(ug)

        # Composite score
        w = self.weights
        m.composite_score = (
            w["nodes"] * m.total_nodes
            + w["edges"] * m.total_edges
            + w["avg_degree"] * m.avg_degree
            + w["max_fan_out"] * m.max_fan_out
            + w["avg_path_length"] * m.avg_path_length
            + w["cycles"] * m.cycle_count
            + w["orphans"] * (m.orphan_nodes + m.orphan_ports)
            + w["cross_community"] * m.cross_community_edges
            + w["density"] * m.density * 100  # Scale density to 0-100 range
        )

        return m

    # ── Path length computation ────────────────────────────────────────────

    def _compute_path_metrics(self, ug: nx.Graph, m: ComplexityMetrics) -> None:
        """Compute avg and max path length, using sampling for large graphs."""
        n_nodes = ug.number_of_nodes()
        if n_nodes < 2:
            return

        if nx.is_connected(ug):
            self._path_metrics_for_graph(ug, m)
        else:
            # Disconnected: weighted average across components
            components = list(nx.connected_components(ug))
            total_path = 0.0
            total_pairs = 0
            max_pl = 0
            for comp in components:
                if len(comp) < 2:
                    continue
                sub = ug.subgraph(comp)
                sub_m = ComplexityMetrics()
                self._path_metrics_for_graph(sub, sub_m)
                n_pairs = len(comp) * (len(comp) - 1)
                total_path += sub_m.avg_path_length * n_pairs
                total_pairs += n_pairs
                max_pl = max(max_pl, sub_m.max_path_length)
            m.avg_path_length = total_path / total_pairs if total_pairs > 0 else 0.0
            m.max_path_length = max_pl

    def _path_metrics_for_graph(self, g: nx.Graph, m: ComplexityMetrics) -> None:
        """Compute path metrics for a single connected graph."""
        n = g.number_of_nodes()
        if n < 2:
            return

        if n <= _SAMPLE_PATH_THRESHOLD:
            # Small graph: exact computation is fine
            m.avg_path_length = nx.average_shortest_path_length(g)
            all_paths = dict(nx.all_pairs_shortest_path_length(g))
            m.max_path_length = max(
                length
                for targets in all_paths.values()
                for length in targets.values()
            )
        else:
            # Large graph: SAMPLE to avoid O(N³)
            # avg_path_length via nx (uses BFS from each node = O(V*(V+E)),
            # still expensive) — sample instead
            nodes_list = list(g.nodes())
            sample_size = min(_SAMPLE_PATH_COUNT, n)
            sample_nodes = random.sample(nodes_list, sample_size)

            total_length = 0
            total_pairs = 0
            max_pl = 0

            for src in sample_nodes:
                lengths = nx.single_source_shortest_path_length(g, src)
                for tgt, dist in lengths.items():
                    if tgt != src:
                        total_length += dist
                        total_pairs += 1
                        max_pl = max(max_pl, dist)

            m.avg_path_length = total_length / total_pairs if total_pairs > 0 else 0.0
            m.max_path_length = max_pl

    # ── Cycle counting ─────────────────────────────────────────────────────

    @staticmethod
    def _count_cycles(g: nx.DiGraph) -> int:
        """Count cycles with a cap to avoid hanging on dense graphs."""
        try:
            count = 0
            for _ in nx.simple_cycles(g):
                count += 1
                if count >= _CYCLE_LIMIT:
                    break
            return count
        except Exception:
            return 0
