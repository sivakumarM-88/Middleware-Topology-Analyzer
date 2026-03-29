"""MQAdapter - parses flat denormalized IBM MQ CSV into TopologyModel."""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

import pandas as pd

from .decision_log import DecisionLog
from .model import (
    ClientRole,
    EdgeType,
    NodeType,
    PortDirection,
    TopologyClient,
    TopologyEdge,
    TopologyModel,
    TopologyNode,
    TopologyPort,
)

# Column name mapping from the flat CSV
COL_QUEUE_NAME = "Discrete Queue Name"
COL_PRODUCER = "ProducerName"
COL_CONSUMER = "ConsumerName"
COL_APP_FULL_NAME = "Primary App_Full_Name"
COL_APP_DISP = "PrimaryAppDisp"
COL_APP_ROLE = "PrimaryAppRole"
COL_PRIMARY_Q_TYPE = "Primary Application"
COL_NEIGHBORHOOD = "Primary Neighborhood"
COL_HOSTING_TYPE = "Primary Hosting Type"
COL_DATA_CLASS = "Primary Data classification"
COL_CRITICAL_PAYMENT = "Primary Enterprise Critical Payment Application"
COL_PCI = "Primary PCI"
COL_PUBLIC = "Primary Publicly Accessible"
COL_TRTC = "Primary TRTC"
COL_Q_TYPE = "q_type"
COL_QM_NAME = "queue_manager_name"
COL_APP_ID = "app_id"
COL_LOB = "line_of_business"
COL_CLUSTER = "cluster_name"
COL_CLUSTER_NL = "cluster_namelist"
COL_PERSISTENCE = "def_persistence"
COL_PUT_RESPONSE = "def_put_response"
COL_INHIBIT_GET = "inhibit_get"
COL_INHIBIT_PUT = "inhibit_put"
COL_REMOTE_QM = "remote_q_mgr_name"
COL_REMOTE_Q = "remote_q_name"
COL_USAGE = "usage"
COL_XMIT_Q = "xmit_q_name"
COL_NEIGHBORHOOD2 = "Neighborhood"


def _is_empty(val) -> bool:
    """Check if a value is empty, NaN, '0', or blank."""
    if val is None:
        return True
    if isinstance(val, float):
        return True  # NaN
    s = str(val).strip()
    return s in ("", "0", "nan", "NaN", "None")


def _clean_str(val, default: str = "") -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    s = str(val).strip()
    return default if s in ("nan", "NaN", "None") else s


def _parse_role(role_str: str) -> ClientRole:
    role_str = role_str.strip().lower()
    if role_str == "producer":
        return ClientRole.PRODUCER
    elif role_str == "consumer":
        return ClientRole.CONSUMER
    return ClientRole.BOTH


def _parse_port_direction(q_type: str) -> PortDirection:
    q_type = q_type.strip().lower()
    if "remote" in q_type and "alias" in q_type:
        return PortDirection.REMOTE  # Remote;Alias → treat as remote
    if "remote" in q_type:
        return PortDirection.REMOTE
    if "alias" in q_type:
        return PortDirection.ALIAS
    return PortDirection.LOCAL


class MQAdapter:
    """Parses a flat denormalized IBM MQ CSV into a TopologyModel.

    Handles deduplication: the same queue appears once per producer/consumer relationship.
    """

    def __init__(self, decision_log: Optional[DecisionLog] = None):
        self.log = decision_log or DecisionLog()

    def parse(self, csv_path: str) -> TopologyModel:
        df = pd.read_csv(csv_path)
        df.columns = df.columns.str.strip()
        model = TopologyModel()

        self._extract_nodes(df, model)
        self._extract_ports(df, model)
        self._extract_clients(df, model)

        model.decision_log = self.log.records
        return model

    def _extract_nodes(self, df: pd.DataFrame, model: TopologyModel) -> None:
        """Extract unique queue managers as TopologyNodes."""
        qm_groups = df.groupby(COL_QM_NAME)

        for qm_name, group in qm_groups:
            qm_name = _clean_str(qm_name)
            if not qm_name:
                continue

            # Aggregate business metadata across all rows for this QM
            pci_count = sum(
                1 for _, r in group.iterrows()
                if _clean_str(r.get(COL_PCI, "")).lower() == "yes"
            )
            critical_count = sum(
                1 for _, r in group.iterrows()
                if _clean_str(r.get(COL_CRITICAL_PAYMENT, "")).lower() == "yes"
            )
            neighborhoods = set()
            lobs = set()
            trtcs = set()
            for _, r in group.iterrows():
                n = _clean_str(r.get(COL_NEIGHBORHOOD, ""))
                if n:
                    neighborhoods.add(n)
                n2 = _clean_str(r.get(COL_NEIGHBORHOOD2, ""))
                if n2:
                    neighborhoods.add(n2)
                lob = _clean_str(r.get(COL_LOB, ""))
                if lob:
                    lobs.add(lob)
                trtc = _clean_str(r.get(COL_TRTC, ""))
                if trtc:
                    trtcs.add(trtc)

            region = next(iter(neighborhoods), "")

            model.nodes[qm_name] = TopologyNode(
                id=qm_name,
                name=qm_name,
                node_type=NodeType.QUEUE_MANAGER,
                region=region,
                business_metadata={
                    "line_of_business": sorted(lobs),
                    "cluster_name": _clean_str(group.iloc[0].get(COL_CLUSTER, "")),
                    "cluster_namelist": _clean_str(group.iloc[0].get(COL_CLUSTER_NL, "")),
                    "neighborhoods": sorted(neighborhoods),
                    "pci_apps_count": pci_count,
                    "critical_payment_apps_count": critical_count,
                    "trtc_classes": sorted(trtcs),
                    "hosting_type": _clean_str(group.iloc[0].get(COL_HOSTING_TYPE, "")),
                },
            )

        self.log.record(
            stage="parsing",
            action="extract_nodes",
            subject_type="model",
            subject_id="all_nodes",
            description=f"Extracted {len(model.nodes)} unique queue managers",
            reason="CSV parsing",
            evidence={"node_count": len(model.nodes)},
        )

    def _extract_ports(self, df: pd.DataFrame, model: TopologyModel) -> None:
        """Extract unique queues as TopologyPorts, deduplicating by (qm, queue_name)."""
        seen: Set[str] = set()

        for _, row in df.iterrows():
            qm = _clean_str(row.get(COL_QM_NAME, ""))
            queue_name = _clean_str(row.get(COL_QUEUE_NAME, ""))
            if not qm or not queue_name:
                continue

            port_id = f"{qm}.{queue_name}"
            if port_id in seen:
                continue
            seen.add(port_id)

            q_type = _clean_str(row.get(COL_Q_TYPE, "Local"))
            direction = _parse_port_direction(q_type)

            remote_qm = _clean_str(row.get(COL_REMOTE_QM, ""))
            remote_q = _clean_str(row.get(COL_REMOTE_Q, ""))
            xmit_q = _clean_str(row.get(COL_XMIT_Q, ""))

            if _is_empty(remote_qm):
                remote_qm = ""
            if _is_empty(remote_q):
                remote_q = ""
            if _is_empty(xmit_q):
                xmit_q = ""

            model.ports[port_id] = TopologyPort(
                id=port_id,
                node_id=qm,
                name=queue_name,
                direction=direction,
                remote_queue=remote_q,
                remote_node_id=remote_qm,
                xmit_queue=xmit_q,
                metadata={
                    "def_persistence": _clean_str(row.get(COL_PERSISTENCE, "")),
                    "def_put_response": _clean_str(row.get(COL_PUT_RESPONSE, "")),
                    "inhibit_get": _clean_str(row.get(COL_INHIBIT_GET, "")),
                    "inhibit_put": _clean_str(row.get(COL_INHIBIT_PUT, "")),
                    "usage": _clean_str(row.get(COL_USAGE, "")),
                    "data_classification": _clean_str(row.get(COL_DATA_CLASS, "")),
                },
            )

        self.log.record(
            stage="parsing",
            action="extract_ports",
            subject_type="model",
            subject_id="all_ports",
            description=f"Extracted {len(model.ports)} unique queues (deduplicated)",
            reason="CSV parsing with deduplication by (QM, queue_name)",
            evidence={"port_count": len(model.ports), "raw_rows": len(df)},
        )

    def _extract_clients(self, df: pd.DataFrame, model: TopologyModel) -> None:
        """Extract unique applications as TopologyClients.

        An app may appear on multiple QMs. We determine the 'home QM' as the one
        where the app has the most non-alias queues with a primary role.
        """
        # Collect per-app data: {app_id: {qm: {"local_count": n, "role": set, ...}}}
        app_qm_data: Dict[str, Dict[str, dict]] = {}
        app_names: Dict[str, str] = {}

        for _, row in df.iterrows():
            app_id = _clean_str(row.get(COL_APP_ID, ""))
            qm = _clean_str(row.get(COL_QM_NAME, ""))
            if not app_id or not qm:
                continue

            app_name = _clean_str(row.get(COL_APP_FULL_NAME, app_id))
            app_names.setdefault(app_id, app_name)

            if app_id not in app_qm_data:
                app_qm_data[app_id] = {}
            if qm not in app_qm_data[app_id]:
                app_qm_data[app_id][qm] = {
                    "local_count": 0,
                    "remote_count": 0,
                    "alias_count": 0,
                    "roles": set(),
                    "ports": [],
                    "metadata": {},
                }

            q_type = _clean_str(row.get(COL_Q_TYPE, "Local"))
            direction = _parse_port_direction(q_type)
            role_str = _clean_str(row.get(COL_APP_ROLE, ""))
            queue_name = _clean_str(row.get(COL_QUEUE_NAME, ""))
            port_id = f"{qm}.{queue_name}"

            entry = app_qm_data[app_id][qm]
            if direction == PortDirection.LOCAL:
                entry["local_count"] += 1
            elif direction == PortDirection.REMOTE:
                entry["remote_count"] += 1
            elif direction == PortDirection.ALIAS:
                entry["alias_count"] += 1

            if role_str:
                entry["roles"].add(role_str.lower())
            if port_id not in entry["ports"]:
                entry["ports"].append(port_id)

            # Capture latest business metadata
            entry["metadata"] = {
                "app_disposition": _clean_str(row.get(COL_APP_DISP, "")),
                "neighborhood": _clean_str(row.get(COL_NEIGHBORHOOD, "")),
                "hosting_type": _clean_str(row.get(COL_HOSTING_TYPE, "")),
                "pci": _clean_str(row.get(COL_PCI, "")).lower() == "yes",
                "enterprise_critical_payment": _clean_str(
                    row.get(COL_CRITICAL_PAYMENT, "")
                ).lower() == "yes",
                "trtc": _clean_str(row.get(COL_TRTC, "")),
                "data_classification": _clean_str(row.get(COL_DATA_CLASS, "")),
            }

        # Elect home QM for each app
        for app_id, qm_map in app_qm_data.items():
            # Score each QM: prefer the one with most local + remote (non-alias) queues
            best_qm = max(
                qm_map.keys(),
                key=lambda qm: (
                    qm_map[qm]["local_count"] + qm_map[qm]["remote_count"],
                    -qm_map[qm]["alias_count"],
                ),
            )

            # Determine role
            all_roles: Set[str] = set()
            all_ports: List[str] = []
            for qm_info in qm_map.values():
                all_roles.update(qm_info["roles"])
                all_ports.extend(qm_info["ports"])

            if "producer" in all_roles and "consumer" in all_roles:
                role = ClientRole.BOTH
            elif "producer" in all_roles:
                role = ClientRole.PRODUCER
            elif "consumer" in all_roles:
                role = ClientRole.CONSUMER
            else:
                role = ClientRole.BOTH

            metadata = qm_map[best_qm]["metadata"]
            client_id = f"{app_id}@{best_qm}"

            model.clients[client_id] = TopologyClient(
                id=client_id,
                app_id=app_id,
                app_name=app_names.get(app_id, app_id),
                home_node_id=best_qm,
                role=role,
                connected_ports=list(set(all_ports)),
                business_metadata=metadata,
            )

            if len(qm_map) > 1:
                self.log.record(
                    stage="parsing",
                    action="elect_home_qm",
                    subject_type="client",
                    subject_id=client_id,
                    description=(
                        f"App {app_id} found on {len(qm_map)} QMs, "
                        f"elected {best_qm} as home QM"
                    ),
                    reason="1-QM-per-app: chose QM with most non-alias queues",
                    evidence={
                        "qm_scores": {
                            qm: {
                                "local": info["local_count"],
                                "remote": info["remote_count"],
                                "alias": info["alias_count"],
                            }
                            for qm, info in qm_map.items()
                        },
                        "elected": best_qm,
                    },
                )

        self.log.record(
            stage="parsing",
            action="extract_clients",
            subject_type="model",
            subject_id="all_clients",
            description=f"Extracted {len(model.clients)} unique application clients",
            reason="CSV parsing with home QM election",
            evidence={"client_count": len(model.clients)},
        )

    def export(self, model: TopologyModel) -> pd.DataFrame:
        """Export a TopologyModel back to the flat CSV format."""
        rows = []

        for client in model.clients.values():
            for port_id in client.connected_ports:
                port = model.ports.get(port_id)
                if port is None:
                    continue
                node = model.nodes.get(port.node_id)
                if node is None:
                    continue

                rows.append({
                    COL_QUEUE_NAME: port.name,
                    COL_PRODUCER: client.app_name if client.role in (ClientRole.PRODUCER, ClientRole.BOTH) else "",
                    COL_CONSUMER: client.app_name if client.role in (ClientRole.CONSUMER, ClientRole.BOTH) else "",
                    COL_APP_FULL_NAME: client.app_name,
                    COL_APP_DISP: client.business_metadata.get("app_disposition", ""),
                    COL_APP_ROLE: client.role.value.capitalize(),
                    COL_PRIMARY_Q_TYPE: port.direction.value.capitalize(),
                    COL_NEIGHBORHOOD: client.business_metadata.get("neighborhood", ""),
                    COL_HOSTING_TYPE: client.business_metadata.get("hosting_type", ""),
                    COL_DATA_CLASS: client.business_metadata.get("data_classification", ""),
                    COL_CRITICAL_PAYMENT: "Yes" if client.business_metadata.get("enterprise_critical_payment") else "No",
                    COL_PCI: "Yes" if client.business_metadata.get("pci") else "No",
                    COL_PUBLIC: "No",
                    COL_TRTC: client.business_metadata.get("trtc", ""),
                    COL_Q_TYPE: port.direction.value.capitalize(),
                    COL_QM_NAME: port.node_id,
                    COL_APP_ID: client.app_id,
                    COL_LOB: node.business_metadata.get("line_of_business", [""])[0] if isinstance(node.business_metadata.get("line_of_business"), list) else node.business_metadata.get("line_of_business", ""),
                    COL_CLUSTER: node.business_metadata.get("cluster_name", ""),
                    COL_CLUSTER_NL: node.business_metadata.get("cluster_namelist", ""),
                    COL_PERSISTENCE: port.metadata.get("def_persistence", ""),
                    COL_PUT_RESPONSE: port.metadata.get("def_put_response", ""),
                    COL_INHIBIT_GET: port.metadata.get("inhibit_get", ""),
                    COL_INHIBIT_PUT: port.metadata.get("inhibit_put", ""),
                    COL_REMOTE_QM: port.remote_node_id or "",
                    COL_REMOTE_Q: port.remote_queue or "",
                    COL_USAGE: port.metadata.get("usage", ""),
                    COL_XMIT_Q: port.xmit_queue or "",
                    COL_NEIGHBORHOOD2: node.region,
                })

        return pd.DataFrame(rows)
