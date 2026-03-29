"""Core data model for TopologyIQ - middleware-agnostic topology representation."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import networkx as nx


class NodeType(str, Enum):
    QUEUE_MANAGER = "queue_manager"
    BROKER = "broker"
    EXCHANGE = "exchange"
    VIRTUAL_HOST = "virtual_host"


class EdgeType(str, Enum):
    CHANNEL = "channel"
    BINDING = "binding"
    REPLICATION = "replication"


class PortDirection(str, Enum):
    LOCAL = "local"
    REMOTE = "remote"
    ALIAS = "alias"
    TRANSMISSION = "transmission"


class ClientRole(str, Enum):
    PRODUCER = "producer"
    CONSUMER = "consumer"
    BOTH = "both"


@dataclass
class TopologyNode:
    id: str
    name: str
    node_type: NodeType
    region: str = ""
    community_id: Optional[int] = None
    is_hub: bool = False
    business_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TopologyEdge:
    id: str
    source_node_id: str
    target_node_id: str
    edge_type: EdgeType
    name: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TopologyPort:
    id: str
    node_id: str
    name: str
    direction: PortDirection
    remote_queue: str = ""
    remote_node_id: str = ""
    xmit_queue: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TopologyClient:
    id: str
    app_id: str
    app_name: str
    home_node_id: str
    role: ClientRole
    connected_ports: List[str] = field(default_factory=list)
    business_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TopologyModel:
    nodes: Dict[str, TopologyNode] = field(default_factory=dict)
    edges: Dict[str, TopologyEdge] = field(default_factory=dict)
    ports: Dict[str, TopologyPort] = field(default_factory=dict)
    clients: Dict[str, TopologyClient] = field(default_factory=dict)
    decision_log: List[Any] = field(default_factory=list)

    def to_networkx(self) -> nx.DiGraph:
        """Build a directed graph of nodes (QMs) connected by edges (channels)."""
        g = nx.DiGraph()
        for node in self.nodes.values():
            g.add_node(node.id, **{
                "name": node.name,
                "node_type": node.node_type.value,
                "region": node.region,
                "community_id": node.community_id,
                "is_hub": node.is_hub,
                **node.business_metadata,
            })
        for edge in self.edges.values():
            g.add_edge(edge.source_node_id, edge.target_node_id, **{
                "id": edge.id,
                "name": edge.name,
                "edge_type": edge.edge_type.value,
                **edge.metadata,
            })
        return g

    def get_undirected_graph(self) -> nx.Graph:
        """Build an undirected graph for community detection (Louvain)."""
        g = nx.Graph()
        for node in self.nodes.values():
            g.add_node(node.id)
        for edge in self.edges.values():
            if g.has_edge(edge.source_node_id, edge.target_node_id):
                g[edge.source_node_id][edge.target_node_id]["weight"] += 1
            else:
                g.add_edge(edge.source_node_id, edge.target_node_id, weight=1)
        return g

    def deep_copy(self) -> TopologyModel:
        """Create a deep copy for what-if analysis."""
        return copy.deepcopy(self)

    def get_clients_on_node(self, node_id: str) -> List[TopologyClient]:
        return [c for c in self.clients.values() if c.home_node_id == node_id]

    def get_ports_on_node(self, node_id: str) -> List[TopologyPort]:
        return [p for p in self.ports.values() if p.node_id == node_id]

    def get_edges_for_node(self, node_id: str) -> List[TopologyEdge]:
        return [
            e for e in self.edges.values()
            if e.source_node_id == node_id or e.target_node_id == node_id
        ]

    def get_communities(self) -> Dict[int, List[str]]:
        """Return {community_id: [node_ids]}."""
        communities: Dict[int, List[str]] = {}
        for node in self.nodes.values():
            if node.community_id is not None:
                communities.setdefault(node.community_id, []).append(node.id)
        return communities

    def get_hubs(self) -> List[str]:
        return [n.id for n in self.nodes.values() if n.is_hub]

    def summary(self) -> Dict[str, int]:
        return {
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "ports": len(self.ports),
            "clients": len(self.clients),
            "decisions": len(self.decision_log),
        }
