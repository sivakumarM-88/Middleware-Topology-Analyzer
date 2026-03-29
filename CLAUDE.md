# CLAUDE.md — TopologyIQ Project Context

## PROJECT OVERVIEW

**Product Name:** TopologyIQ  
**Tagline:** "Graph intelligence for middleware topology optimization"  
**Team Name:** (to be decided — leaning funny)  
**Context:** Wells Fargo internal hackathon — IBM MQ topology simplification  

TopologyIQ is a graph-theory-powered, middleware-agnostic topology management platform. It has three modes: optimize existing topologies, onboard new applications, and converse with the topology via an AI chatbot. The same engine works for IBM MQ today, Kafka/RabbitMQ tomorrow — just swap the adapter.

---

## HACKATHON PROBLEM STATEMENT (EXACT REQUIREMENTS)

### Problem
Enterprise IBM MQ environments have grown into dense, highly interconnected networks over many years. They exhibit:
- Excessive queue manager sprawl
- Complex routing paths
- Tightly coupled application dependencies
- Large numbers of point-to-point channels with unclear ownership
- Brittle routing and lack of standardization
- Slow onboarding and high manual effort for provisioning

### Mission
Rethink how MQ environments are designed and managed. Demonstrate how legacy MQ topologies can be transformed into simplified, standardized, future-ready architectures.

### Input Data Format
A single flat denormalized CSV file (can be 20K+ rows). Each row represents a queue-to-application relationship with all metadata embedded. **This is NOT multiple separate CSVs — it's one wide table.**

### Core Constraints (MUST be enforced — violations = invalid solution)
1. **Exactly one queue manager per application — BIDIRECTIONAL** (1 QM per AppID AND 1 App per QM). 
   - FORWARD: Each application connects to exactly ONE queue manager (no app scattered across multiple QMs)
   - REVERSE: Each queue manager is DEDICATED to exactly ONE application (no QM shared by multiple apps)
   - "Applications connect only to THEIR OWN queue manager" means DEDICATED/EXCLUSIVE.
   - If 2 apps share a QM today (communicating via local queues), in the target state they MUST each get their own dedicated QM and communicate via remote queues + channels instead.
   - THIS IS THE MOST IMPORTANT CONSTRAINT. It drives the entire target state transformation. At scale (20K rows), most QMs will be shared by multiple apps — splitting them creates more QMs, and hub-spoke keeps the resulting channels manageable.
2. **Producers write to a Local Queue with remote queue attribute** (called "remoteQ") within their own QM. The remoteQ leverages a transmission queue ("xmitq") to send messages via server channels to another QM.
3. **Queue managers communicate via sender/receiver channels.** Channels have deterministic naming pairs (fromQM.toQM / toQM.fromQM). **Channels do NOT exist in the input data — teams must infer and introduce them.**
4. **Consumers read from local queues.** These local queues receive data from their channel.

### Topology Simplification Goals
- Reduce total number of channels and routing hops without reducing application capabilities
- Eliminate redundant or unused MQ objects
- Avoid cycles and excessive fan-in/fan-out patterns
- Define and apply a quantitative complexity metric

### Target State Requirements
- Clean ownership of queue managers and queues
- Predictable and deterministic message routing
- Secure-by-default configuration
- Output expressed as CSV, suitable for automation

### Expected Deliverables
1. **Target-state topology dataset** in CSV format identical to the input CSV structure
2. **Complexity analysis** — a complexity algorithm and the complexity calculation on the input dataset vs the target dataset
3. **Topology visualizations** — demonstrate how the topology is the ideal topology
4. **Design and decision documentation**

### Success Criteria (what judges evaluate)
1. All constraints correctly enforced
2. Clear and explainable design decisions
3. Demonstrated reduction in complexity
4. Applicability to real enterprise MQ environments

---

## ACTUAL INPUT CSV SCHEMA (from analyzing sample data)

The input is a **single flat CSV** with one sheet named `MQ.Sample.Data.cleaned_v001`. Each row is a queue-to-app relationship. Real dataset has ~20K rows. Columns discovered:

### Column mapping (from left to right as seen in screenshots)
```
A  - Discrete Queue Name        → Queue name (TopologyPort identifier)
B  - ProducerName               → Producer application full name
C  - ConsumerName               → Consumer application full name
D  - Primary App_Full_Name      → Primary application name
E  - PrimaryAppDisp             → App disposition: "Full App Retire, Mainframe", "Mainframe", "Private PaaS", "Private IaaS, Private PaaS"
F  - PrimaryAppRole             → "Producer" or "Consumer"
G  - Primary Application        → Queue type: "Remote", "Local", "Alias", "Remote;Alias"
H  - Primary Neighborhood       → Business domain: "Consumer Lending", "Core Banking", "Wholesale Banking"
I  - Primary Hosting Type       → "Internal"
J  - Primary Data classification → "Confidential", "Internal Use"
K  - Primary Enterprise Critical Payment Application → "No" (likely "Yes" for critical ones)
L  - Primary PCI                → "No" or "Yes" — PCI compliance flag
M  - Primary Publicly Accessible → "No"
N  - Primary TRTC               → Recovery time: "00= 0-30 Minutes", "02= 2 Hours to 4 Hours", "03= 4:01 to 11:59 Hours"
O  - q_type                     → Queue type: "Remote", "Local", "Alias"
P  - queue_manager_name         → QM name (TopologyNode identifier): e.g., "WL6EX2C", "WQ26", "WL6ER2D"
Q  - app_id                     → Application identifier: "8A", "OK", "PPCSM", "8AFK"
R  - line_of_business           → "TECHCT", "TECHCCIBT"
S  - cluster_name               → Cluster number (all "7" in sample)
T  - cluster_namelist           → Cluster namelist (all "7" in sample)
U  - def_persistence            → "No" or "Yes"
V  - def_put_response           → "Synchronous"
W  - inhibit_get                → "Enabled" or blank
X  - inhibit_put                → "Enabled" or "0 Enabled"
Y  - remote_q_mgr_name          → Remote QM name (for remote/alias queues): e.g., "WQ26"
Z  - remote_q_name              → Remote queue name: e.g., "8A.OK.VFHVIGL.HDF"
AA - usage                      → "Normal" or blank
AB - xmit_q_name                → Transmission queue name: e.g., "OK.WQ26", or "0"
AC - Neighborhood               → "Mainframe" or "Wholesale Banking"
```

### Key observations from sample data
1. **Queue names encode message flow**: `8A.OK.VFHVIGL.HDF.RQST` — the `8A.OK` prefix indicates communication between app 8A and app OK. `.RQST` = request, `.XA21` = alias suffix.
2. **XMIT queue names encode target QM**: `OK.WQ26` — xmit queue routing to QM WQ26.
3. **Remote queues have populated remote_q_mgr_name and xmit_q_name**; local queues have these blank or "0".
4. **Alias queues** (q_type="Alias") have remote_q_mgr_name populated but NOT xmit_q_name — they resolve locally.
5. **Column G ("Primary Application")** contains "Remote", "Local", "Remote;Alias" — this is the ROLE-specific queue type, which can differ from column O (q_type). A single Discrete Queue Name can appear in multiple rows with different roles.
6. **Each row is NOT a unique queue** — the same queue appears once for the producer relationship and once for the consumer relationship. Must deduplicate.
7. **CRITICAL: QM WL6ER2D is shared by apps PPCSM and 8AFK** — this is a CONSTRAINT VIOLATION. The target state must split this into two dedicated QMs. This is the MOST COMMON violation pattern you'll see in the 20K-row dataset. The "1 QM per app" constraint is BIDIRECTIONAL: no app on multiple QMs AND no QM shared by multiple apps.

### Sample data flows reconstructed

**Flow 1: Cross-QM remote messaging (Consumer Lending / Core Banking)**
```
DFCeth (app_id=8A, Producer, Mainframe)
  → connects to QM WL6EX2C
  → PUTs to remote queue "8A.OK.VFHVIGL.HDF.RQST"
  → routes via xmit queue "OK.WQ26"
  → [INFERRED sender channel: WL6EX2C.TO.WQ26]
  → arrives at QM WQ26
  → alias "8A.OK.VFHVIGL.HDF.RQST.XA21" resolves to local queue
  → OOIKN JIU (app_id=OK, Consumer, Core Banking) GETs from WQ26
```

**Flow 2: Local messaging on SHARED QM — CONSTRAINT VIOLATION (Wholesale Banking)**
```
AS-IS (VIOLATION — two apps sharing one QM):
Hdc - Hdxknvlr (app_id=8AFK, Producer+Consumer, Wholesale Banking)
PP Arcne VMU (app_id=PPCSM, Producer+Consumer, Wholesale Banking)
  → both connect to QM WL6ER2D
  → communicate via local queues: ZEEWALA.ACK, ZEEWALA.DAT, ARCNE.ACK
  → THIS VIOLATES "1 QM per app" — two apps share WL6ER2D

TARGET (after Stage 1 split):
8AFK (primary — most ports) KEEPS original QM WL6ER2D:
  → 8AFK reads from local queue (arrived via channel from WL6ER2D_PPCSM)
  → 8AFK writes to local queue → remote queue → xmit queue → channel to WL6ER2D_PPCSM

WL6ER2D_PPCSM (new, dedicated to PPCSM):
  → PPCSM writes to local queue → remote queue → xmit queue → channel to WL6ER2D
  → PPCSM reads from local queue (arrived via channel from WL6ER2D)

Channels created:
  WL6ER2D.TO.WL6ER2D_PPCSM (sender) + WL6ER2D_PPCSM.FROM.WL6ER2D (receiver)
  WL6ER2D_PPCSM.TO.WL6ER2D (sender) + WL6ER2D.FROM.WL6ER2D_PPCSM (receiver)

Original QM WL6ER2D: KEPT (reused by primary app 8AFK)
```

---

## ABSTRACT DATA MODEL (Middleware-Agnostic)

### TopologyNode
Represents a messaging infrastructure node.
```python
@dataclass
class TopologyNode:
    id: str                    # QM name, e.g., "WL6EX2C"
    name: str                  # Display name
    node_type: NodeType        # QUEUE_MANAGER | BROKER | EXCHANGE | VIRTUAL_HOST
    region: str                # Neighborhood/region
    business_metadata: dict    # {
                               #   "line_of_business": "TECHCT",
                               #   "cluster_name": "7",
                               #   "neighborhood": "Mainframe",
                               #   "hosting_type": "Internal",
                               #   "pci_apps_count": 2,
                               #   "critical_payment_apps_count": 1,
                               #   "min_trtc": "00= 0-30 Minutes"
                               # }
```
**MQ mapping:** Queue Manager  
**Kafka mapping:** Broker  
**RabbitMQ mapping:** Virtual Host  

### TopologyEdge
Represents a communication link between nodes. **In MQ, these are INFERRED from the data, not directly present.**
```python
@dataclass
class TopologyEdge:
    id: str                    # "WL6EX2C->WQ26:WL6EX2C.TO.WQ26"
    source_node_id: str        # "WL6EX2C"
    target_node_id: str        # "WQ26"
    edge_type: EdgeType        # CHANNEL | BINDING | REPLICATION
    name: str                  # "WL6EX2C.TO.WQ26" (generated by naming engine)
    channel_type: str          # "sender" or "receiver" (MQ-specific in metadata)
    metadata: dict
```
**MQ mapping:** Sender/Receiver channel pair  
**Channel inference rule:** For every unique (queue_manager_name, remote_q_mgr_name) pair where remote_q_mgr_name is non-empty and non-zero, create a bidirectional channel pair.

### TopologyPort
Represents a message endpoint on a node.
```python
class PortDirection(Enum):
    LOCAL = "local"
    REMOTE = "remote"
    ALIAS = "alias"            # ADDED during design review — MQ alias queues
    TRANSMISSION = "transmission"

@dataclass
class TopologyPort:
    id: str                    # "WL6EX2C.8A.OK.VFHVIGL.HDF.RQST"
    node_id: str               # "WL6EX2C"
    name: str                  # "8A.OK.VFHVIGL.HDF.RQST"
    direction: PortDirection   # REMOTE
    remote_queue: str          # "8A.OK.VFHVIGL.HDF" (target queue name)
    remote_node_id: str        # "WQ26" (target QM)
    xmit_queue: str            # "OK.WQ26"
    metadata: dict             # {
                               #   "def_persistence": "No",
                               #   "def_put_response": "Synchronous",
                               #   "inhibit_get": "Enabled",
                               #   "inhibit_put": "Enabled",
                               #   "usage": "Normal",
                               #   "data_classification": "Confidential"
                               # }
```

### TopologyClient
Represents an application connecting to the topology.
```python
class ClientRole(Enum):
    PRODUCER = "producer"
    CONSUMER = "consumer"

@dataclass
class TopologyClient:
    id: str                    # "8A@WL6EX2C"
    app_id: str                # "8A"
    app_name: str              # "DFCeth - HUVY MIPKNVL ZYU"
    home_node_id: str          # "WL6EX2C" (the ONE QM this app connects to)
    role: ClientRole           # PRODUCER
    connected_ports: list      # List of port_ids this client reads/writes
    business_metadata: dict    # {
                               #   "app_disposition": "Full App Retire, Mainframe",
                               #   "neighborhood": "Consumer Lending",
                               #   "hosting_type": "Internal",
                               #   "pci": False,
                               #   "enterprise_critical_payment": False,
                               #   "trtc": "03= 4:01 to 11:59 Hours",
                               #   "data_classification": "Confidential"
                               # }
```

### TopologyModel (the container)
```python
@dataclass
class TopologyModel:
    nodes: Dict[str, TopologyNode]
    edges: Dict[str, TopologyEdge]
    ports: Dict[str, TopologyPort]
    clients: Dict[str, TopologyClient]
    decision_log: List[DecisionRecord]

    def to_networkx(self) -> nx.DiGraph: ...
    def get_undirected_graph(self) -> nx.Graph: ...  # For Louvain
    def get_complexity_score(self) -> ComplexityMetrics: ...
```

---

## ADAPTER DESIGN

### MQAdapter
Handles the flat denormalized CSV from the hackathon. The key challenge: **deduplication**. The same queue appears in multiple rows (once per producer/consumer relationship). The adapter must:

1. **Extract unique QMs** from column P (queue_manager_name) → TopologyNodes
2. **Extract unique queues** from column A (Discrete Queue Name) + column O (q_type) → TopologyPorts
3. **Extract unique apps** from column Q (app_id) + column D (Primary App_Full_Name) → TopologyClients
4. **Infer channels** from (queue_manager_name, remote_q_mgr_name) pairs → TopologyEdges
5. **Aggregate business metadata** per QM (e.g., count of PCI apps, minimum TRTC across all apps on that QM)

```python
class MQAdapter(MiddlewareAdapter):
    def parse(self, csv_path: str) -> TopologyModel: ...
    def export(self, model: TopologyModel) -> pd.DataFrame: ...  # Same schema as input
```

### CRITICAL ADAPTER LOGIC: Home QM Election

The constraint says "1 QM per app." But in the flat CSV, an app_id can appear on multiple QMs because the CSV shows both sides of a message flow (producer QM and consumer QM).

**Rule to determine actual connectivity:**
- Producer + (Remote or Local) queue on a QM → app ACTUALLY CONNECTS to this QM
- Consumer + Local queue on a QM → app ACTUALLY CONNECTS to this QM  
- app_id appearing on a QM only via Alias → NOT a connection, just a routing reference
- If an app genuinely connects to multiple QMs (constraint violation), elect the "home QM" as the one where the app has the most local queues (or highest traffic)

### Future Adapters (pluggable via Strategy pattern)
- `KafkaAdapter` — parse broker configs + topic metadata
- `RabbitMQAdapter` — parse exchange/binding/queue definitions
- `CustomAdapter` — any middleware with nodes + edges + ports + clients

---

## OPTIMIZATION PIPELINE (6 stages)

### Stage 0: Graph Discovery [NEW — added during design review]
**Purpose:** Build the graph from evidence in the data. Channels don't exist in the input.
**Logic:**
1. Scan all ports where `remote_q_mgr_name` is non-empty and non-zero
2. For each unique (source_qm, target_qm) pair, create a TopologyEdge
3. Classify all ports by direction: Local, Remote, Alias, Transmission
4. Build the initial as-is graph
5. Record discovery findings in decision log

### Stage 1: Constraint Enforcement [CRITICAL — REWRITTEN after design review]
**Purpose:** Enforce the BIDIRECTIONAL 1-QM-per-app rule.

**THE CONSTRAINT IS BIDIRECTIONAL:**
- Forward: Each app connects to exactly ONE QM (no app scattered across multiple QMs)
- Reverse: Each QM is DEDICATED to exactly ONE app (no QM shared by multiple apps)
- "Applications connect only to THEIR OWN queue manager" means DEDICATED, not shared.
- This means: if 2 apps share a QM today (local communication), in the target state they each get their OWN QM and communicate via remote queues + channels.

**This is the MOST IMPORTANT constraint. Violations include:**
- App on multiple QMs (forward violation) — needs consolidation
- Multiple apps on one QM (reverse violation) — needs QM SPLIT
- The reverse violation is the more common one in legacy topologies and the one that drives most of the target state transformation.

**Stage 1a — Split shared QMs (reverse constraint):**
1. For each QM, count distinct app_ids connected to it
2. If a QM has > 1 app_id → it must be SPLIT
3. Elect **primary app** = the one with the most connected ports (non-alias). Primary app **keeps the original QM**.
4. For each **secondary app** on the shared QM:
   a. Create a new dedicated QM. Naming: `{ORIGINAL_QM}_{APP_ID}`, e.g., `WL6ER2D_PPCSM`.
   b. Move secondary app's exclusive queues to the new QM
   c. What was previously LOCAL communication between co-located apps now becomes CROSS-QM communication:
      - On each side: create a REMOTE queue pointing to the other QM
      - On each side: create a XMIT queue (PortDirection.TRANSMISSION) for the other QM
      - Create a sender/receiver channel pair between original QM and new QM
      - Local queues on each side receive data via the channel
   d. Record each split as a DecisionRecord: reason="QM shared by multiple apps, constraint requires 1 QM per app", evidence={primary_app, moved_app, shared_queues, ...}
5. Original QM is **kept** (reused by primary app) — no orphan QMs created

**Stage 1b — Consolidate scattered apps (forward constraint):**
1. Group clients by app_id
2. For each app on multiple QMs, determine actual connectivity (see adapter logic)
3. Elect home QM: the QM where app has primary role + most non-alias queues
4. Migrate: update client.home_node_id, recreate queues on home QM, remove from non-home QMs
5. Record each migration as a DecisionRecord with reason + evidence

**EXAMPLE from sample data:**
```
AS-IS: WL6ER2D hosts both PPCSM and 8AFK (VIOLATION — shared QM)
  WL6ER2D
    ├── PPCSM writes to ZEEWALA.ACK (local)
    ├── 8AFK reads from ZEEWALA.ACK (local)
    ├── 8AFK writes to ARCNE.ACK (local)
    └── PPCSM reads from ARCNE.ACK (local)

TARGET: Primary app keeps original QM, secondary gets new QM
  WL6ER2D (original QM, kept by primary app 8AFK)
    ├── 8AFK reads from local queue (receives via channel from WL6ER2D_PPCSM)
    ├── 8AFK writes to local queue → remote queue → xmit queue → channel to WL6ER2D_PPCSM
    └── existing edges to other QMs (e.g., WQ26) stay intact

  WL6ER2D_PPCSM (new, dedicated to PPCSM)
    ├── PPCSM writes to local queue → remote queue → xmit queue → channel to WL6ER2D
    └── PPCSM reads from local queue (receives via channel from WL6ER2D)

  Channels:
    WL6ER2D.TO.WL6ER2D_PPCSM (sender) + WL6ER2D_PPCSM.FROM.WL6ER2D (receiver)
    WL6ER2D_PPCSM.TO.WL6ER2D (sender) + WL6ER2D.FROM.WL6ER2D_PPCSM (receiver)
```

**WHY THIS MATTERS AT SCALE:**
- 20K rows likely has many QMs shared by 5-10 apps each
- Splitting creates MORE QMs but each is clean and dedicated
- Primary app keeps the original QM (preserves existing edges, no orphans)
- Only secondary apps get new QMs — minimizes churn
- This is where Louvain + hub-spoke (Stage 3-4) becomes ESSENTIAL
- Without hub-spoke, the split would create N² channels between all the new QMs
- Hub-spoke keeps the channel count at O(N) instead of O(N²)
- The optimization narrative: "We split for correctness, then optimize for efficiency"

### Stage 2: Dead Object Pruning
**Purpose:** Remove unused MQ objects.
**Logic:**
1. Find orphan QMs: no clients connected, no active channels with traffic
2. Find orphan queues: no producer AND no consumer referencing them
3. Find unused aliases: alias resolving to a removed queue
4. Find dead channels: no message flow path (source or target QM is orphaned)
5. Remove all. Record each removal.

### Stage 3: Community Detection (Louvain)
**Purpose:** Find natural clusters of QMs that communicate heavily.
**Logic:**
1. Build undirected graph from QM-to-QM edges
2. Run Louvain community detection algorithm (python-louvain library)
3. Each community = a group of QMs that exchange most of their traffic internally
4. **Guard:** If a community has < 3 members, skip hub-spoke for that community (already simple enough)
5. Annotate each node with its community_id
6. Record community assignments

### Stage 4: Hub Election + Spoke Wiring [REVISED — added business metadata weighting]
**Purpose:** Transform N*(N-1) mesh channels into N spoke channels per community.
**Logic:**
1. For each community with 3+ members:
   a. Compute betweenness centrality for each QM within the community
   b. Compute business criticality score: weight PCI apps, TRTC class, payment-critical flags
   c. Hub = argmax(0.6 * centrality + 0.4 * business_criticality)
   d. Remove all direct inter-spoke channels
   e. Create spoke → hub and hub → spoke channel pairs
   f. Cross-community traffic: create hub-to-hub backbone channels
2. Record each hub election with evidence (centrality value, business score)
3. Record each channel replacement with complexity delta

### Stage 5: Queue + Channel Rationalization
**Purpose:** Standardize naming, wire the complete message path.
**Logic:**
After Stage 1 (split), every app has its own dedicated QM. Therefore ALL inter-app communication is cross-QM. The "same QM local queue" case ONLY applies to an app producing and consuming its own messages (self-loop, rare).

1. For each message flow (producer app → consumer app):
   a. Producer and consumer are ALWAYS on different QMs (because 1 QM per app)
   b. If both QMs are in the same community:
      - Producer's QM: local queue (app writes here) → remote queue → xmit queue → sender channel to hub
      - Hub QM: receiver channel → forwarding logic → sender channel to consumer's QM
      - Consumer's QM: receiver channel → local queue (app reads here)
   c. If QMs are in different communities:
      - Producer QM → producer's hub → [backbone channel] → consumer's hub → consumer QM
   d. Direct spoke-to-spoke: if two apps communicate heavily and are in the same community, a direct channel MAY be more efficient than routing through the hub. Record the tradeoff in decision log.
2. Apply naming engine to all generated objects
3. Decide alias retention: keep aliases only if they serve an active routing purpose (explainer justifies)
4. Generate target CSV in same schema as input

---

## NAMING CONVENTION ENGINE

### Queue Naming Pattern
```
{PRODUCER_APPID}.{CONSUMER_APPID}.{SYSTEM}.{FUNCTION}.{SUFFIX}

SUFFIX values:
  RQST — request message
  RESP — response message
  ACK  — acknowledgment
  DAT  — data transfer
  ERR  — error/dead letter
```

### Channel Naming Pattern
```
Sender:   {FROM_QM}.TO.{TO_QM}
Receiver: {TO_QM}.FROM.{FROM_QM}
```

### XMIT Queue Naming Pattern
```
{TARGET_QM_NAME}
(One xmit queue per target QM on each source QM)
```

### Alias Naming Pattern (if retained)
```
{ORIGINAL_QUEUE_NAME}.XA{VERSION}
```

The naming engine is pluggable — organizations can provide a template/convention and the engine applies it consistently. The engine also validates generated names against MQ naming rules (max length, allowed characters, etc.).

---

## COMPLEXITY SCORING ENGINE

### Formula
```
C = w1 * |nodes|
  + w2 * |edges|
  + w3 * avg_degree
  + w4 * max_fan_out
  + w5 * avg_path_length
  + w6 * cycle_count
  + w7 * orphan_objects
  + w8 * cross_community_edges
  + w9 * density
```

### Weights and Rationale
```
w1 (nodes) = 1.0       — baseline count
w2 (edges) = 2.0       — channels are expensive to manage
w3 (avg_degree) = 5.0  — measures connectivity sprawl
w4 (max_fan_out) = 8.0 — a QM with 15 outbound channels is a SPOF
w5 (avg_path_length) = 10.0 — more hops = more latency + failure points
w6 (cycles) = 15.0     — cycles create routing ambiguity, operational risk
w7 (orphans) = 3.0     — clutter, security surface
w8 (cross_community) = 4.0 — cross-cluster traffic adds complexity
w9 (density) = 20.0    — highest weight — fully-connected mesh is worst case
```

### ComplexityMetrics dataclass
```python
@dataclass
class ComplexityMetrics:
    total_nodes: int
    total_edges: int
    total_ports: int
    total_clients: int
    avg_degree: float
    max_fan_out: int
    max_fan_in: int
    avg_path_length: float
    max_path_length: int
    cycle_count: int
    orphan_nodes: int
    orphan_ports: int
    unused_edges: int
    communities: int
    cross_community_edges: int
    density: float
    composite_score: float      # The weighted sum
```

### Scoring Rules
- Score computed at EVERY stage boundary (stages 0-5)
- Dashboard shows a waterfall chart: as-is score → delta at each stage → target score
- Each stage's contribution is independently visible
- For Mode 2 (onboarding), score delta is computed for each new app added

---

## DECISION LOG

Every transformation is recorded:

```python
@dataclass
class DecisionRecord:
    id: str                     # UUID
    timestamp: datetime
    stage: str                  # "graph_discovery", "constraint_enforcement", etc.
    action: str                 # "infer_channel", "migrate_app", "remove_orphan", "elect_hub", etc.
    subject_type: str           # "node", "edge", "port", "client"
    subject_id: str             # The ID of the thing being changed
    description: str            # Human-readable: "Migrated APP_PAYMENTS from QM_EAST_03 to QM_EAST_01"
    reason: str                 # "1-QM-per-app constraint violated"
    evidence: dict              # {"old_qm_count": 3, "home_qm_local_queues": 5, "other_qm_local_queues": [1, 2]}
    from_state: dict            # State before change
    to_state: dict              # State after change
    complexity_delta: float     # Change in composite score
    confidence: float           # 0.0-1.0
```

The decision log is:
- Searchable and filterable in the dashboard
- Input to the AI explainer agent for generating design documentation
- Input to the conversational agent for answering "why" questions
- Exportable as part of the design document deliverable

---

## THREE USER-FACING MODES

### Mode 1: Optimize (Batch Transformation)
**User flow:**
1. Upload as-is CSV (20K rows)
2. System runs preprocessor → adapter → graph discovery
3. Inventory scan shown: X QMs, Y queues, Z apps, N violations, M orphans
4. User clicks "Run Optimizer"
5. Pipeline stages 1-5 execute with progress indication
6. Complexity waterfall builds in real time
7. Side-by-side topology visualization: as-is (hairball) vs target (hub-spoke)
8. User reviews, can switch to Chat mode for questions/refinements
9. Export: target CSV + complexity report + visualizations + design document

### Mode 2: Onboard New Application
**User flow:**
1. User fills form: app name, role (producer/consumer), target app to connect to, neighborhood, hosting type, PCI flag, TRTC class
2. Placement algorithm runs against CURRENT target topology. New app ALWAYS gets its own dedicated QM (constraint: 1 app = 1 QM). The question is where to place it:
   - Option A: join same community as target app → spoke channel to hub, hub routes to target → lowest complexity
   - Option B: join different community matching new app's neighborhood → needs hub-to-hub backbone channel
   - Option C: direct channel to target app's QM → bypasses hub, simpler but adds non-standard channel
   - Recommendation based on: neighborhood match, PCI compatibility, community size, complexity delta
3. Naming engine generates all MQ objects (queues, channels, xmit queues)
4. Output: human-readable setup guide + MQSC commands + CSV rows to append
5. Complexity delta displayed: "Adding this app increases score by X"
6. Graph updated — target topology now includes the new app
7. All future queries reflect the updated state

**Placement algorithm detail:**
```python
def recommend_placement(new_app, target_app, target_topology):
    # CRITICAL: New app ALWAYS gets its own dedicated QM (1 app = 1 QM constraint)
    # The question is: which community should the new QM join?
    
    # 1. Where does target_app live?
    target_qm = target_topology.get_home_qm(target_app)
    target_community = target_topology.get_community(target_qm)
    
    # 2. Create new dedicated QM for the new app
    new_qm = create_dedicated_qm(new_app)  # e.g., QM_RISK_ENGINE
    
    # 3. Score placement options (which community to join)
    options = []
    
    # Option A: Join same community as target app
    # New QM becomes a spoke in target's community, connects via hub
    # 1 channel pair to hub, hub routes to target app's QM
    delta_a = score_delta_same_community(new_qm, target_community)
    options.append(("same_community", target_community, delta_a,
                    "Lowest complexity — routes through existing hub"))
    
    # Option B: Join a different community (if neighborhood mismatch)
    # New QM joins the community matching its neighborhood
    # Needs cross-community hub-to-hub channel
    if new_app.neighborhood != target_community.neighborhood:
        matching_community = find_community_for_neighborhood(new_app.neighborhood)
        delta_b = score_delta_cross_community(new_qm, matching_community, target_community)
        options.append(("neighborhood_match", matching_community, delta_b,
                        "Matches neighborhood but needs hub-to-hub routing"))
    
    # Option C: Direct channel to target (skip hub)
    # Only if traffic volume justifies bypassing hub
    delta_c = score_delta_direct_channel(new_qm, target_qm)
    options.append(("direct_channel", None, delta_c,
                    "Direct spoke-to-spoke — simpler but adds a non-hub channel"))
    
    # Rank by complexity delta (lowest = best)
    return sorted(options, key=lambda x: x[2])
```

### Mode 3: Converse with Topology (Chatbot)
**Architecture:** Claude API (Sonnet 4) with the full graph + decision log serialized as context.

**Five conversation categories:**

1. **Query** — "Where does app 8AFK live?" "How many channels does WQ26 have?" "List all apps in Wholesale Banking."
   - Agent queries the in-memory graph
   - Returns structured answer

2. **What-if** — "What if we retire QM WL6EX2C?" "What if we merge communities A and B?"
   - Agent creates a copy of the graph
   - Applies the hypothetical change
   - Computes impact: affected apps, new channels needed, migrations, complexity delta
   - Returns impact report WITHOUT modifying the real topology
   - User can then say "Apply this change"

3. **Refinement** — "Move app X to QM Y" "I don't want WL6ER2D as hub, use WL6ER2F instead"
   - Agent modifies the target topology
   - Recomputes complexity score
   - Shows tradeoff: "This increases complexity by X because Y"
   - Records as a DecisionRecord with stage="user_refinement"

4. **Explanation** — "Why did you pick WL6ER2D as hub?" "Why was QM_LEGACY_07 removed?"
   - Agent looks up DecisionRecords for the subject
   - Synthesizes a natural language explanation with evidence
   - References specific metrics: centrality, PCI count, TRTC, etc.

5. **Generation** — "Give me MQSC commands for the target" "Generate the design document" "Export CSV rows for app RISK_ENGINE"
   - Agent generates requested output from the current topology state
   - MQSC commands include: DEFINE QLOCAL, DEFINE QREMOTE, DEFINE CHANNEL, etc.
   - Design document structured by decision type, with evidence tables

**Chat context management:**
```python
def build_chat_context(topology: TopologyModel) -> str:
    """Serialize the topology + decision log for Claude's context window."""
    return f"""
    You are the TopologyIQ conversational agent.
    
    CURRENT TOPOLOGY STATE:
    - {len(topology.nodes)} queue managers: {list(topology.nodes.keys())}
    - {len(topology.edges)} channels: {[e.name for e in topology.edges.values()]}
    - {len(topology.ports)} queues
    - {len(topology.clients)} applications
    - Communities: {topology.get_communities()}
    - Hubs: {topology.get_hubs()}
    - Complexity score: {topology.get_complexity_score().composite_score}
    
    DECISION LOG (last 50 decisions):
    {serialize_decision_log(topology.decision_log[-50:])}
    
    NAMING CONVENTIONS:
    Queue: {{PROD}}.{{CONS}}.{{SYSTEM}}.{{FUNCTION}}.{{SUFFIX}}
    Channel: {{FROM_QM}}.TO.{{TO_QM}}
    
    You can: answer queries, evaluate what-ifs, apply refinements, explain decisions, generate configs.
    Always show complexity delta for any topology change.
    Always reference specific evidence from the decision log when explaining.
    """
```

---

## DASHBOARD DESIGN

### Layout
Four tabs across the top:

**Tab 1: Overview**
- Top row: 4 metric cards (QMs count with delta, Channels count with delta, Apps count, Complexity score with % reduction)
- Middle: Complexity waterfall chart (as-is → stage deltas → target)
- Bottom: Decision log stream (scrollable, searchable, filterable by stage/action type)
- Each decision shows: badge (stage), description, complexity delta

**Tab 2: Topology Explorer**
- Side-by-side D3 force-directed graphs
- Left = as-is topology (messy hairball), Right = target topology (clean hub-spoke)
- Nodes colored by Louvain community
- Hub nodes are larger
- Click any node → panel shows: QM name, queues, apps, channels, community, business metadata
- Click any edge → panel shows: channel name, source/target, type, message flows using this channel
- Controls: toggle orphans, toggle aliases, filter by neighborhood, zoom/pan
- Node size proportional to number of connected apps

**Tab 3: Onboard App**
- Guided form with fields:
  - App name (text)
  - App ID (text)
  - Role (dropdown: Producer / Consumer)
  - Connect to app (searchable dropdown of existing apps)
  - Neighborhood (dropdown from existing neighborhoods)
  - Hosting type (dropdown)
  - PCI (toggle)
  - TRTC (dropdown)
- Submit → Placement recommendation with 2-3 options ranked by complexity delta
- Each option shows: QM name, required objects, complexity delta, reasoning
- Accept → generates full setup: instructions + MQSC + CSV rows
- Topology explorer updates to reflect the new app

**Tab 4: Chat**
- Full chat interface
- Message history with user/AI bubbles
- The AI agent has full graph context
- Supports all 5 conversation categories
- When agent suggests topology changes, show "Apply" / "Reject" buttons
- When agent generates configs/documents, show "Download" button
- Topology explorer updates live when changes are applied

### Tech Implementation
- Frontend: React + Vite
- Graphs: D3.js force-directed layout
- Charts: Recharts (waterfall, bar charts)
- Styling: Tailwind CSS
- Chat: WebSocket connection to FastAPI backend
- State: React Context or Zustand for topology state

---

## TECHNOLOGY STACK

### Backend
```
Python 3.11+
FastAPI          — REST API + WebSocket for chat
NetworkX         — Graph algorithms (path analysis, centrality, cycle detection)
python-louvain   — Louvain community detection (community.best_partition)
Pandas           — CSV read/write, data preprocessing
Pydantic         — Data model validation
Anthropic SDK    — Claude API for AI agents (use claude-sonnet-4-20250514)
uvicorn          — ASGI server
```

### Frontend
```
React 18+        — UI framework
Vite             — Build tool
D3.js            — Force-directed topology visualization
Recharts         — Waterfall chart, metric charts
Tailwind CSS     — Styling
```

### API Endpoints (FastAPI)
```
POST   /api/upload          — Upload CSV, return parsed topology summary
POST   /api/optimize        — Run optimization pipeline, return target topology
GET    /api/topology/as-is  — Get as-is topology graph data (for D3)
GET    /api/topology/target — Get target topology graph data (for D3)
GET    /api/metrics         — Get complexity metrics (as-is vs target)
GET    /api/decisions       — Get decision log (paginated, filterable)
POST   /api/onboard         — Submit new app onboarding request
POST   /api/chat            — Send chat message, get AI response
WS     /ws/chat             — WebSocket for streaming chat
GET    /api/export/csv      — Download target CSV
GET    /api/export/report   — Download complexity report
GET    /api/export/mqsc     — Download MQSC provisioning commands
```

---

## PROJECT STRUCTURE

```
topologyiq/
├── CLAUDE.md                          # This file
├── README.md                          # Project overview
├── backend/
│   ├── requirements.txt
│   ├── main.py                        # FastAPI app entry point
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── model.py                   # TopologyNode, Edge, Port, Client, Model
│   │   ├── adapter.py                 # MQAdapter (flat CSV parser)
│   │   ├── discovery.py               # Stage 0: graph discovery + channel inference
│   │   ├── optimizer.py               # Stages 1-5 pipeline orchestrator
│   │   ├── constraints.py             # Stage 1: constraint enforcement
│   │   ├── pruner.py                  # Stage 2: dead object pruning
│   │   ├── community.py               # Stage 3: Louvain community detection
│   │   ├── hub_election.py            # Stage 4: hub election + spoke wiring
│   │   ├── rationalizer.py            # Stage 5: queue/channel rationalization
│   │   ├── scorer.py                  # Complexity scoring engine
│   │   ├── naming.py                  # Queue/channel naming convention engine
│   │   ├── onboarding.py              # Mode 2: new app placement + setup generation
│   │   └── decision_log.py            # DecisionRecord tracking
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── inventory.py               # Inventory agent (discovery + anomaly detection)
│   │   ├── optimizer_agent.py         # Optimizer agent (pipeline orchestration)
│   │   └── chat_agent.py             # Conversational agent (Claude API integration)
│   └── api/
│       ├── __init__.py
│       ├── routes.py                  # REST endpoints
│       └── websocket.py              # WebSocket chat handler
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── tailwind.config.js
│   ├── index.html
│   └── src/
│       ├── App.jsx                    # Main app with tab navigation
│       ├── main.jsx                   # Entry point
│       ├── components/
│       │   ├── Overview.jsx           # Tab 1: metrics + waterfall + decision log
│       │   ├── TopologyExplorer.jsx   # Tab 2: D3 force-directed side-by-side
│       │   ├── OnboardApp.jsx         # Tab 3: guided onboarding form
│       │   ├── Chat.jsx              # Tab 4: chatbot interface
│       │   ├── MetricCard.jsx        # Reusable metric card component
│       │   ├── WaterfallChart.jsx    # Complexity waterfall using Recharts
│       │   ├── DecisionLog.jsx       # Searchable decision stream
│       │   ├── ForceGraph.jsx        # D3 force-directed graph wrapper
│       │   └── MQSCOutput.jsx        # MQSC command display/copy
│       ├── hooks/
│       │   ├── useTopology.js        # Topology state management
│       │   └── useChat.js            # WebSocket chat hook
│       └── utils/
│           ├── api.js                # API client
│           └── formatters.js         # Number formatting, etc.
└── sample_data/
    └── MQ.Sample.Data.cleaned_v001.csv
```

---

## BUILD ORDER (recommended sequence)

### Phase 1: Core Engine (build first — everything depends on this)
1. `model.py` — All dataclasses and enums
2. `decision_log.py` — DecisionRecord dataclass
3. `adapter.py` — MQAdapter CSV parser (handle the flat denormalized schema)
4. `scorer.py` — ComplexityMetrics + weighted scoring
5. `naming.py` — Queue/channel naming engine
6. `discovery.py` — Stage 0: channel inference
7. `constraints.py` — Stage 1: 1-QM-per-app enforcement
8. `pruner.py` — Stage 2: dead object removal
9. `community.py` — Stage 3: Louvain clustering
10. `hub_election.py` — Stage 4: hub election with business weighting
11. `rationalizer.py` — Stage 5: queue/channel standardization
12. `optimizer.py` — Pipeline orchestrator (chains stages 0-5)
13. `onboarding.py` — New app placement algorithm

### Phase 2: API Layer
14. `main.py` — FastAPI app setup
15. `routes.py` — REST endpoints
16. `websocket.py` — WebSocket handler

### Phase 3: AI Agents
17. `inventory.py` — Inventory agent
18. `optimizer_agent.py` — Optimizer agent
19. `chat_agent.py` — Conversational agent with Claude API

### Phase 4: Frontend
20. Project setup (Vite + React + Tailwind + D3 + Recharts)
21. `App.jsx` — Tab navigation shell
22. `ForceGraph.jsx` — D3 force-directed graph component (hardest, do first)
23. `Overview.jsx` — Metrics + waterfall
24. `TopologyExplorer.jsx` — Side-by-side topology view
25. `OnboardApp.jsx` — Guided form
26. `Chat.jsx` — Chat interface

### Phase 5: Integration + Polish
27. Wire frontend to backend API
28. Test with sample data
29. Test with full 20K-row dataset
30. Polish visualizations and chat UX

---

## COMPETITIVE DIFFERENTIATORS (why we win)

1. **Graph algorithms, not scripts** — Louvain community detection + betweenness centrality. Provably optimal, not manually designed.
2. **Middleware-agnostic** — Abstract model with adapter pattern. Same engine for Kafka/RabbitMQ tomorrow.
3. **Three modes** — Not just an optimizer but a platform: optimize + onboard + converse.
4. **Explainable AI** — Every decision has evidence, reason, and complexity delta. Judges can ask "why" and get a real answer.
5. **Quantitative scoring** — Weighted complexity formula with waterfall showing each algorithm's contribution.
6. **Business-aware optimization** — Hub election considers PCI, TRTC, payment criticality — not just graph metrics.
7. **Automation-ready output** — Target CSV in same schema + MQSC commands. Ready to provision, not just a design doc.

---

## DEMO SCRIPT (40 seconds)

1. **(15s) Upload + Optimize** — Drop the 20K-row CSV. Force-directed graph transforms from hairball to hub-spoke. Waterfall shows 62% complexity reduction.
2. **(10s) Onboard New App** — "Add RISK_ENGINE consuming from PPCSM." Instant placement recommendation + generated queue names + MQSC commands.
3. **(10s) What-If Query** — "What if we retire QM_LEGACY_07?" Impact analysis with migration plan and complexity delta.
4. **(5s) Explain Decision** — "Why this hub?" AI answers with centrality + PCI + TRTC evidence.

---

## IMPORTANT EDGE CASES TO HANDLE

1. **Apps that are both producer AND consumer** — e.g., 8AFK is both producer and consumer on WL6ER2D. The client should have a combined role or two separate client entries. After QM split, the app still has both roles on its dedicated QM.
2. **Queue type "Remote;Alias"** — Column G shows this. A queue can serve as both remote and alias. Handle in PortDirection or as metadata.
3. **Empty/zero values in remote columns** — remote_q_mgr_name can be empty, "0", or blank. All mean "not a remote queue."
4. **Cluster columns** — All "7" in sample data. Might have real cluster info in full dataset. Use as TopologyNode metadata.
5. **Multiple queue names for same flow** — e.g., RQST and XA21 variants. These are the same logical flow, different physical objects. Group them.
6. **Circular flows** — App A → App B and App B → App A. These create bidirectional channels. The optimizer should handle cycles correctly (don't break bidirectional communication). After QM split, both directions need their own channel pairs.
7. **PCI isolation** — PCI apps might need to stay on dedicated QMs. Since every app gets its own QM after split, PCI isolation is naturally achieved. But the HUB QM for a PCI community should also be PCI-compliant.
8. **Scale** — 20K rows. All algorithms must work efficiently. NetworkX handles this fine. Pandas handles CSV parsing. UI needs pagination for decision log.
9. **Idempotency** — Running the optimizer twice on the same input should produce the same output.
10. **Export fidelity** — Target CSV must have EXACTLY the same columns as input CSV. No missing columns, no extra columns, no schema changes.
11. **QM split creates channel explosion** — If a QM has 10 apps, primary keeps the original QM and 9 secondary apps get new QMs. If all 10 communicated locally before, they now need up to 9*10=90 channel pairs. THIS IS WHY HUB-SPOKE IS ESSENTIAL. Without it, the split makes things worse. The pipeline narrative: "Split for correctness (Stage 1), then optimize for efficiency (Stages 3-4)."
12. **QM naming after split** — Primary app keeps the original QM name. Secondary apps get `{ORIGINAL_QM}_{APP_ID}` (e.g., `WL6ER2D_PPCSM`). Deterministic and non-conflicting.
13. **Hub QMs are infrastructure, not app-owned** — Hub QMs introduced in Stage 4 don't belong to any app. They are pure routing infrastructure. No app connects directly to a hub. Messages pass through via channels. This means hub QMs are an EXCEPTION to the "1 app per QM" rule — they have ZERO apps, they just route.
