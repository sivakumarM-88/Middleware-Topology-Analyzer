"""Complexity scoring engine for topology analysis."""

from __future__ import annotations

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

        # Path length (use undirected for connectedness)
        if ug.number_of_nodes() > 1 and nx.is_connected(ug):
            m.avg_path_length = nx.average_shortest_path_length(ug)
            all_paths = dict(nx.all_pairs_shortest_path_length(ug))
            m.max_path_length = max(
                length
                for targets in all_paths.values()
                for length in targets.values()
            )
        elif ug.number_of_nodes() > 1:
            # For disconnected graphs, compute per-component and take weighted avg
            components = list(nx.connected_components(ug))
            total_path = 0.0
            total_pairs = 0
            max_pl = 0
            for comp in components:
                if len(comp) < 2:
                    continue
                sub = ug.subgraph(comp)
                apl = nx.average_shortest_path_length(sub)
                n_pairs = len(comp) * (len(comp) - 1)
                total_path += apl * n_pairs
                total_pairs += n_pairs
                all_paths = dict(nx.all_pairs_shortest_path_length(sub))
                comp_max = max(
                    length
                    for targets in all_paths.values()
                    for length in targets.values()
                )
                max_pl = max(max_pl, comp_max)
            m.avg_path_length = total_path / total_pairs if total_pairs > 0 else 0.0
            m.max_path_length = max_pl

        # Cycles (directed)
        try:
            cycles = list(nx.simple_cycles(g))
            m.cycle_count = len(cycles)
        except Exception:
            m.cycle_count = 0

        # Orphan nodes: QMs with no clients
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
