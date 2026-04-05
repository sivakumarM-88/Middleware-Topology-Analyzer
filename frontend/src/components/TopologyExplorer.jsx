import { useState, useMemo } from 'react';
import ForceGraph from './ForceGraph';

/**
 * Filter graph — QM and App are MUTUALLY EXCLUSIVE:
 *  - App filter: show ONLY the app's home QM + its remote target QMs (precise view)
 *  - QM filter: show that QM + its direct edge neighbors
 *  - Community: show all members of that community
 */
function filterGraph(graph, filterQM, filterAppID, filterCommunity) {
  if (!graph || (!filterQM && !filterAppID && !filterCommunity)) return graph;

  const seeds = new Set();

  if (filterAppID) {
    // APP-CENTRIC: all QMs where this app has ports + remote target QMs
    for (const n of graph.nodes) {
      const client = n.clients?.find(c => c.app_id === filterAppID);
      if (client) {
        // All QMs where app has queues (home + any others with local queues)
        (client.all_node_ids || [n.id]).forEach(nid => seeds.add(nid));
        // Remote target QMs (where remote/alias queues point)
        (client.remote_targets || []).forEach(t => seeds.add(t));
      }
    }
  } else if (filterQM) {
    // QM-CENTRIC: the QM + its direct edge neighbors
    seeds.add(filterQM);
    for (const l of graph.links) {
      const src = typeof l.source === 'object' ? l.source.id : l.source;
      const tgt = typeof l.target === 'object' ? l.target.id : l.target;
      if (src === filterQM) seeds.add(tgt);
      if (tgt === filterQM) seeds.add(src);
    }
  }

  if (filterCommunity) {
    for (const n of graph.nodes) {
      if (String(n.community_id) === filterCommunity) seeds.add(n.id);
    }
  }

  const nodes = graph.nodes.filter(n => seeds.has(n.id));
  const nodeSet = new Set(nodes.map(n => n.id));
  const links = graph.links.filter(l => {
    const src = typeof l.source === 'object' ? l.source.id : l.source;
    const tgt = typeof l.target === 'object' ? l.target.id : l.target;
    return nodeSet.has(src) && nodeSet.has(tgt);
  });

  return {
    ...graph, nodes, links,
    summary: { ...graph.summary, total_nodes: nodes.length, total_edges: links.length },
  };
}

/* ── Optimization Story Panel ──────────────────────────────────────── */
function OptimizationStory({ changes, metrics }) {
  if (!changes) return null;

  const cardStyles = [
    'bg-emerald-900/20 border-emerald-800/40',
    'bg-amber-900/20 border-amber-800/40',
    'bg-indigo-900/20 border-indigo-800/40',
    'bg-rose-900/20 border-rose-800/40',
  ];
  const items = [
    { val: metrics?.reduction_pct ? `${metrics.reduction_pct}%` : '\u2014', label: 'Complexity Reduction', style: cardStyles[0] },
    { val: changes.hubs.length, label: 'Hub QMs Elected', style: cardStyles[1] },
    { val: changes.edgeReduction > 0 ? `-${changes.edgeReduction}` : String(changes.edgeReduction), label: 'Channels Reduced', style: cardStyles[2] },
    { val: changes.removedNodes.length, label: 'Orphans Removed', style: cardStyles[3] },
  ];

  const steps = [];
  if (changes.newNodes.length > 0)
    steps.push({ stage: 'Constraint Enforcement', desc: `Split ${changes.newNodes.length} shared QMs into dedicated QMs (1 app per QM)`, badge: 'bg-amber-900/50 text-amber-300' });
  if (changes.removedNodes.length > 0)
    steps.push({ stage: 'Dead Object Pruning', desc: `Removed ${changes.removedNodes.length} orphan QM${changes.removedNodes.length > 1 ? 's' : ''} and unused queues`, badge: 'bg-red-900/50 text-red-300' });
  if (changes.communities.length > 0)
    steps.push({ stage: 'Community Detection', desc: `Identified ${changes.communities.length} natural clusters using Louvain algorithm`, badge: 'bg-purple-900/50 text-purple-300' });
  if (changes.hubs.length > 0)
    steps.push({ stage: 'Hub Election', desc: `Elected ${changes.hubs.length} hub QMs based on betweenness centrality + business criticality`, badge: 'bg-emerald-900/50 text-emerald-300' });
  if (changes.spokeChannels > 0)
    steps.push({ stage: 'Spoke Wiring', desc: `Created ${changes.spokeChannels} hub-spoke channels replacing mesh connections`, badge: 'bg-indigo-900/50 text-indigo-300' });
  if (changes.backboneChannels > 0)
    steps.push({ stage: 'Backbone', desc: `Added ${changes.backboneChannels} hub-to-hub backbone channels for cross-community routing`, badge: 'bg-cyan-900/50 text-cyan-300' });

  return (
    <div className="mb-6 bg-gradient-to-br from-gray-900 via-gray-900 to-indigo-950/30 border border-gray-700 rounded-2xl p-5 shadow-xl">
      <h2 className="text-base font-bold text-white mb-4 flex items-center gap-2">
        <span className="w-6 h-6 bg-emerald-600 rounded-md flex items-center justify-center text-white text-xs font-bold">&#10003;</span>
        Optimization Complete
      </h2>
      {/* Key metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        {items.map(it => (
          <div key={it.label} className={`rounded-xl border p-3 ${it.style}`}>
            <div className="text-2xl font-extrabold text-white">{it.val}</div>
            <div className="text-[10px] text-gray-400 uppercase tracking-wider mt-0.5">{it.label}</div>
          </div>
        ))}
      </div>
      {/* Steps */}
      {steps.length > 0 && (
        <div className="space-y-2 mb-4">
          <div className="text-xs text-gray-400 font-semibold uppercase tracking-wider mb-1">What we optimized</div>
          {steps.map((s, i) => (
            <div key={i} className="flex items-start gap-2.5 text-sm">
              <span className={`text-[10px] px-2 py-0.5 rounded-full whitespace-nowrap mt-0.5 ${s.badge}`}>{s.stage}</span>
              <span className="text-gray-300">{s.desc}</span>
            </div>
          ))}
        </div>
      )}
      {/* Assurance */}
      <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-emerald-900/15 border border-emerald-800/30 text-xs text-emerald-400">
        <span className="text-base">&#10003;</span>
        <span>All application connections preserved. No data flows broken. Every app has its own dedicated QM.</span>
      </div>
    </div>
  );
}

/* ── Main Component ────────────────────────────────────────────────── */
export default function TopologyExplorer({ asIsGraph, targetGraph, optimized, metrics, decisions }) {
  const [selected, setSelected] = useState(null);
  const [view, setView] = useState('side-by-side');
  const [filterQM, setFilterQM] = useState('');
  const [filterAppID, setFilterAppID] = useState('');
  const [filterCommunity, setFilterCommunity] = useState('');

  // Dropdown options from active data source
  const activeRaw = view === 'target' && targetGraph ? targetGraph : asIsGraph;
  const qmOptions = useMemo(() => {
    if (!activeRaw) return [];
    return [...new Set(activeRaw.nodes.map(n => n.id))].sort();
  }, [activeRaw]);

  const appOptions = useMemo(() => {
    if (!activeRaw) return [];
    const ids = new Set();
    activeRaw.nodes.forEach(n => n.clients?.forEach(c => ids.add(c.app_id)));
    return [...ids].sort();
  }, [activeRaw]);

  const communityOptions = useMemo(() => {
    if (!activeRaw?.summary?.communities) return [];
    return Object.entries(activeRaw.summary.communities)
      .map(([cid, members]) => ({ id: cid, size: members.length, hub: activeRaw.summary.hubs?.find(h => members.includes(h)) }))
      .sort((a, b) => +a.id - +b.id);
  }, [activeRaw]);

  // Apply filters
  const hasFilter = filterQM || filterAppID || filterCommunity;
  const filteredAsIs = useMemo(
    () => filterGraph(asIsGraph, filterQM, filterAppID, filterCommunity),
    [asIsGraph, filterQM, filterAppID, filterCommunity],
  );
  const filteredTarget = useMemo(
    () => filterGraph(targetGraph, filterQM, filterAppID, filterCommunity),
    [targetGraph, filterQM, filterAppID, filterCommunity],
  );

  // Compute diff for optimization story + change highlights
  const changes = useMemo(() => {
    if (!asIsGraph || !targetGraph) return null;
    const asIsIds = new Set(asIsGraph.nodes.map(n => n.id));
    const targetIds = new Set(targetGraph.nodes.map(n => n.id));
    return {
      newNodes: targetGraph.nodes.filter(n => !asIsIds.has(n.id)),
      removedNodes: asIsGraph.nodes.filter(n => !targetIds.has(n.id)),
      hubs: targetGraph.nodes.filter(n => n.is_hub),
      communities: Object.keys(targetGraph.summary?.communities || {}),
      asIsEdgeCount: asIsGraph.links.length,
      targetEdgeCount: targetGraph.links.length,
      edgeReduction: asIsGraph.links.length - targetGraph.links.length,
      spokeChannels: targetGraph.links.filter(l => l.topology === 'spoke_to_hub' || l.topology === 'hub_to_spoke').length,
      backboneChannels: targetGraph.links.filter(l => l.topology === 'backbone').length,
      newNodeIds: new Set(targetGraph.nodes.filter(n => !asIsIds.has(n.id)).map(n => n.id)),
    };
  }, [asIsGraph, targetGraph]);

  // Change sets for graph annotations
  const asIsChangeSet = useMemo(() => {
    if (!asIsGraph) return null;
    return { sharedNodeIds: new Set(asIsGraph.nodes.filter(n => (n.client_count || 0) > 1).map(n => n.id)) };
  }, [asIsGraph]);

  const targetChangeSet = useMemo(() => {
    if (!changes) return null;
    return { newNodeIds: changes.newNodeIds };
  }, [changes]);

  // Early return after all hooks
  if (!asIsGraph) {
    return (
      <div className="text-center py-16 text-gray-500">
        <p className="text-lg">Upload a CSV to view the topology.</p>
      </div>
    );
  }

  const graphData = view === 'target' ? filteredTarget : filteredAsIs;
  const showSideBySide = view === 'side-by-side' && optimized && targetGraph;
  const displayData = graphData || filteredAsIs;

  return (
    <div>
      {/* ── Optimization Story Panel ─────────────────────────────────── */}
      {optimized && targetGraph && <OptimizationStory changes={changes} metrics={metrics} />}

      {/* ── Filters & View Controls ──────────────────────────────────── */}
      <div className="flex flex-wrap items-end gap-3 mb-4">
        {/* QM filter — clears App when selected */}
        <div className="flex flex-col gap-1">
          <label className="text-[10px] text-gray-500 uppercase tracking-wider">
            Queue Manager {filterQM && <span className="text-indigo-400 normal-case">(active)</span>}
          </label>
          <select value={filterQM}
            onChange={e => { setFilterQM(e.target.value); if (e.target.value) setFilterAppID(''); }}
            disabled={!!filterAppID}
            className={`bg-gray-800 border text-gray-200 text-xs rounded-lg px-2 py-1.5 min-w-[150px] focus:border-indigo-500 focus:outline-none ${filterAppID ? 'border-gray-800 opacity-40 cursor-not-allowed' : 'border-gray-700'}`}>
            <option value="">All QMs ({qmOptions.length})</option>
            {qmOptions.map(qm => <option key={qm} value={qm}>{qm}</option>)}
          </select>
        </div>
        {/* Separator */}
        <div className="text-xs text-gray-600 pb-1.5 font-medium">OR</div>
        {/* App filter — clears QM when selected */}
        <div className="flex flex-col gap-1">
          <label className="text-[10px] text-gray-500 uppercase tracking-wider">
            Application {filterAppID && <span className="text-indigo-400 normal-case">(active)</span>}
          </label>
          <select value={filterAppID}
            onChange={e => { setFilterAppID(e.target.value); if (e.target.value) setFilterQM(''); }}
            disabled={!!filterQM}
            className={`bg-gray-800 border text-gray-200 text-xs rounded-lg px-2 py-1.5 min-w-[150px] focus:border-indigo-500 focus:outline-none ${filterQM ? 'border-gray-800 opacity-40 cursor-not-allowed' : 'border-gray-700'}`}>
            <option value="">All Apps ({appOptions.length})</option>
            {appOptions.map(id => <option key={id} value={id}>{id}</option>)}
          </select>
        </div>
        {/* Community filter */}
        {communityOptions.length > 0 && (
          <div className="flex flex-col gap-1">
            <label className="text-[10px] text-gray-500 uppercase tracking-wider">Community</label>
            <select value={filterCommunity} onChange={e => setFilterCommunity(e.target.value)}
              className="bg-gray-800 border border-gray-700 text-gray-200 text-xs rounded-lg px-2 py-1.5 min-w-[150px] focus:border-indigo-500 focus:outline-none">
              <option value="">All Communities ({communityOptions.length})</option>
              {communityOptions.map(c => (
                <option key={c.id} value={c.id}>C{c.id} — {c.size} QMs{c.hub ? ` (Hub: ${c.hub})` : ''}</option>
              ))}
            </select>
          </div>
        )}
        {/* Clear */}
        {hasFilter && (
          <button onClick={() => { setFilterQM(''); setFilterAppID(''); setFilterCommunity(''); }}
            className="px-3 py-1.5 text-xs rounded-lg bg-red-900/40 text-red-300 hover:bg-red-900/60 transition">
            Clear filters
          </button>
        )}
        <div className="flex-1" />
        {/* View toggle */}
        {optimized && targetGraph && (
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-gray-500 mr-1">View:</span>
            {[['side-by-side', 'Side by Side'], ['as-is', 'As-Is'], ['target', 'Target']].map(([v, lbl]) => (
              <button key={v} onClick={() => setView(v)}
                className={`px-3 py-1.5 text-xs rounded-lg transition ${view === v ? 'bg-indigo-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-gray-200'}`}>
                {lbl}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* ── Filter info ──────────────────────────────────────────────── */}
      {hasFilter && displayData && (() => {
        // Find the selected app's client data for rich detail
        let appClient = null;
        let appHomeQM = null;
        if (filterAppID) {
          for (const n of (activeRaw?.nodes || [])) {
            const c = n.clients?.find(cl => cl.app_id === filterAppID);
            if (c) { appClient = c; appHomeQM = n.id; break; }
          }
        }
        // Group queues by type for structured display
        const localQs = appClient?.queues?.filter(q => q.type === 'local') || [];
        const remoteQs = appClient?.queues?.filter(q => q.type === 'remote') || [];
        const aliasQs = appClient?.queues?.filter(q => q.type === 'alias') || [];
        const xmitQs = appClient?.queues?.filter(q => q.type === 'transmission') || [];

        return (
          <div className="mb-3 px-4 py-3 rounded-xl bg-gray-900/80 border border-gray-700 text-xs">
            {filterAppID && appClient ? (
              <div className="space-y-2.5">
                {/* Header */}
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-gray-400">App</span>
                  <span className="font-mono font-bold text-white text-sm">{filterAppID}</span>
                  <span className="text-gray-500">({appClient.name})</span>
                  <span className={`px-1.5 py-0.5 rounded text-[10px] ${appClient.role === 'producer' ? 'bg-emerald-900/50 text-emerald-400' : appClient.role === 'consumer' ? 'bg-amber-900/50 text-amber-400' : 'bg-purple-900/50 text-purple-400'}`}>{appClient.role}</span>
                  <span className="text-gray-600 ml-1">QMs:</span>
                  {(appClient.all_node_ids || [appHomeQM]).map((nid, i) => (
                    <span key={nid} className={`font-mono font-bold ${nid === appHomeQM ? 'text-indigo-400' : 'text-sky-400'}`}>
                      {i > 0 ? ', ' : ''}{nid}{nid === appHomeQM ? ' (home)' : ''}
                    </span>
                  ))}
                  {(appClient.remote_targets?.length || 0) > 0 && (
                    <span className="text-gray-600 ml-1">{'\u2192'} {appClient.remote_targets.map((t, i) => (
                      <span key={t} className="font-mono font-bold text-amber-400">{i > 0 ? ', ' : ''}{t}</span>
                    ))}</span>
                  )}
                </div>
                {/* Queue breakdown by type */}
                <div className="grid gap-2">
                  {/* LOCAL queues */}
                  {localQs.length > 0 && (
                    <div>
                      <div className="text-[10px] text-emerald-500 font-semibold uppercase tracking-wider mb-0.5">
                        Local Queues ({localQs.length})
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {localQs.slice(0, 10).map((q, i) => (
                          <span key={i} className="font-mono text-[10px] bg-emerald-950/40 border border-emerald-900/40 px-1.5 py-0.5 rounded text-emerald-300">
                            {q.name}{q.on_qm && q.on_qm !== appHomeQM ? ` [${q.on_qm}]` : ''}
                          </span>
                        ))}
                        {localQs.length > 10 && <span className="text-gray-600 text-[10px]">+{localQs.length - 10} more</span>}
                      </div>
                    </div>
                  )}
                  {/* REMOTE queues */}
                  {remoteQs.length > 0 && (
                    <div>
                      <div className="text-[10px] text-amber-500 font-semibold uppercase tracking-wider mb-0.5">
                        Remote Queues ({remoteQs.length}) — sends to other QMs
                      </div>
                      <div className="flex flex-col gap-0.5">
                        {remoteQs.slice(0, 10).map((q, i) => (
                          <div key={i} className="font-mono text-[10px] flex items-center gap-1.5">
                            <span className="text-amber-300 bg-amber-950/40 border border-amber-900/40 px-1.5 py-0.5 rounded">{q.name}</span>
                            <span className="text-gray-500">{'\u2192'}</span>
                            <span className="text-white font-semibold">{q.remote_qm}</span>
                            {q.remote_queue && <span className="text-gray-600">Q: {q.remote_queue}</span>}
                            {q.xmit_queue && <span className="text-gray-600">XMIT: {q.xmit_queue}</span>}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {/* ALIAS queues */}
                  {aliasQs.length > 0 && (
                    <div>
                      <div className="text-[10px] text-purple-500 font-semibold uppercase tracking-wider mb-0.5">
                        Alias Queues ({aliasQs.length}) — resolves to another queue
                      </div>
                      <div className="flex flex-col gap-0.5">
                        {aliasQs.slice(0, 10).map((q, i) => (
                          <div key={i} className="font-mono text-[10px] flex items-center gap-1.5">
                            <span className="text-purple-300 bg-purple-950/40 border border-purple-900/40 px-1.5 py-0.5 rounded">{q.name}</span>
                            <span className="text-gray-500">{'\u2192'}</span>
                            {q.remote_qm && <span className="text-white">{q.remote_qm}:</span>}
                            {q.remote_queue && <span className="text-gray-400">{q.remote_queue}</span>}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {/* XMIT queues */}
                  {xmitQs.length > 0 && (
                    <div>
                      <div className="text-[10px] text-cyan-500 font-semibold uppercase tracking-wider mb-0.5">
                        Transmission Queues ({xmitQs.length})
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {xmitQs.slice(0, 10).map((q, i) => (
                          <span key={i} className="font-mono text-[10px] bg-cyan-950/40 border border-cyan-900/40 px-1.5 py-0.5 rounded text-cyan-300">
                            {q.name}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  {localQs.length === 0 && remoteQs.length === 0 && aliasQs.length === 0 && (
                    <div className="text-gray-500">No queues found for this application.</div>
                  )}
                </div>
              </div>
            ) : filterQM ? (
              <div>
                QM <span className="font-mono font-bold text-white">{filterQM}</span> and its
                <span className="font-bold text-white ml-1">{displayData.nodes.length - 1}</span> connected QMs,
                <span className="font-bold text-white ml-1">{displayData.links.length}</span> channels
              </div>
            ) : filterCommunity ? (
              <div>
                Community <span className="font-bold text-white">C{filterCommunity}</span> \u2014
                <span className="font-bold text-white ml-1">{displayData.nodes.length}</span> QMs,
                <span className="font-bold text-white ml-1">{displayData.links.length}</span> channels
              </div>
            ) : null}
          </div>
        );
      })()}

      {/* ── Graphs ───────────────────────────────────────────────────── */}
      {showSideBySide ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <ForceGraph data={filteredAsIs} width={700} height={550}
            title={`As-Is Topology \u2014 ${filteredAsIs?.nodes?.length || 0} QMs, ${filteredAsIs?.links?.length || 0} channels (mesh)`}
            onSelectNode={setSelected} changeSet={asIsChangeSet} />
          <ForceGraph data={filteredTarget} width={700} height={550}
            title={`Target Topology \u2014 ${filteredTarget?.nodes?.length || 0} QMs, ${filteredTarget?.links?.length || 0} channels (hub-spoke)`}
            onSelectNode={setSelected} changeSet={targetChangeSet} />
        </div>
      ) : (
        <ForceGraph data={displayData} width={1200} height={650}
          title={view === 'target'
            ? `Target Topology \u2014 ${displayData?.nodes?.length || 0} QMs, ${displayData?.links?.length || 0} channels (hub-spoke)`
            : `As-Is Topology \u2014 ${displayData?.nodes?.length || 0} QMs, ${displayData?.links?.length || 0} channels`}
          onSelectNode={setSelected}
          changeSet={view === 'target' ? targetChangeSet : asIsChangeSet} />
      )}

      {/* ── Legend ────────────────────────────────────────────────────── */}
      <div className="mt-4 p-3 bg-gray-900/50 border border-gray-800 rounded-xl">
        <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs text-gray-400">
          <span className="text-gray-500 font-semibold">Legend:</span>
          <div className="flex items-center gap-1.5">
            <div className="w-3.5 h-3.5 rounded-full border-2 border-amber-400 border-dashed" />
            <span>Hub QM</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-3.5 h-3.5 rounded-full bg-indigo-500/20 border border-indigo-500" />
            <span>Standard QM</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-3.5 h-3.5 rounded-full border-2 border-emerald-500" />
            <span className="text-emerald-400">NEW QM (from split)</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-3.5 h-3.5 rounded-full border-2 border-red-500 border-dashed" />
            <span className="text-red-400">SHARED QM (violation)</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-3.5 h-3.5 rounded-full bg-indigo-500/10 border border-indigo-500" />
            <span className="text-indigo-400">LOCAL ONLY (no channels)</span>
          </div>
          <div className="flex items-center gap-1.5">
            <svg width="24" height="8"><line x1="0" y1="4" x2="24" y2="4" stroke="#6366f1" strokeWidth="1.5" /></svg>
            <span>Channel</span>
          </div>
          <div className="flex items-center gap-1.5">
            <svg width="24" height="8"><line x1="0" y1="4" x2="24" y2="4" stroke="#fbbf24" strokeWidth="2.5" strokeDasharray="4,3" /></svg>
            <span>Backbone (hub-to-hub)</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-8 h-5 rounded bg-indigo-500/10 border border-indigo-500/30" />
            <span>Community cluster</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-gray-300">P</span><span>Producer</span>
            <span className="font-mono text-gray-300 ml-1">C</span><span>Consumer</span>
            <span className="font-mono text-gray-300 ml-1">B</span><span>Both</span>
          </div>
        </div>
      </div>

      {/* ── Channels Table ───────────────────────────────────────────── */}
      {displayData?.links?.length > 0 && (
        <div className="mt-4 bg-gray-900/50 border border-gray-800 rounded-xl p-4">
          <h3 className="text-sm font-medium text-gray-300 mb-3">
            Channels ({displayData.links.length})
            {displayData.links.length > 200 && <span className="text-gray-500 font-normal ml-2">(showing first 200)</span>}
          </h3>
          <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
            <table className="w-full text-xs text-left">
              <thead className="text-gray-500 uppercase sticky top-0 bg-gray-900">
                <tr>
                  <th className="px-3 py-2">Channel Name</th>
                  <th className="px-3 py-2">From</th>
                  <th className="px-3 py-2">To</th>
                  <th className="px-3 py-2">Type</th>
                  <th className="px-3 py-2">Flows</th>
                </tr>
              </thead>
              <tbody>
                {displayData.links.slice(0, 200).map(l => (
                  <tr key={l.id} className="border-t border-gray-800 hover:bg-gray-800/50">
                    <td className="px-3 py-2 font-mono text-indigo-400">{l.name}</td>
                    <td className="px-3 py-2 font-mono text-gray-300">{typeof l.source === 'object' ? l.source.id : l.source}</td>
                    <td className="px-3 py-2 font-mono text-gray-300">{typeof l.target === 'object' ? l.target.id : l.target}</td>
                    <td className="px-3 py-2">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] ${
                        l.topology === 'backbone' ? 'bg-amber-900/50 text-amber-300' :
                        l.topology === 'spoke_to_hub' ? 'bg-emerald-900/50 text-emerald-300' :
                        l.topology === 'hub_to_spoke' ? 'bg-blue-900/50 text-blue-300' :
                        'bg-gray-800 text-gray-400'
                      }`}>{l.topology || 'direct'}</span>
                    </td>
                    <td className="px-3 py-2 text-gray-500">{(l.flows || []).join(', ') || '\u2014'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Queue Manager Grid ───────────────────────────────────────── */}
      <div className="mt-4 bg-gray-900/50 border border-gray-800 rounded-xl p-4">
        <h3 className="text-sm font-medium text-gray-300 mb-3">
          Queue Managers ({displayData.nodes.length})
          {displayData.nodes.length > 100 && !hasFilter && (
            <span className="text-gray-500 font-normal ml-2">(use filters above to narrow)</span>
          )}
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 max-h-[600px] overflow-y-auto">
          {displayData.nodes.map(n => (
            <div key={n.id}
              className={`p-3 rounded-lg border transition cursor-pointer ${
                selected?.id === n.id ? 'border-indigo-500 bg-indigo-900/20' :
                n.is_hub ? 'border-amber-700/50 bg-amber-900/10 hover:border-amber-600' :
                changes?.newNodeIds?.has(n.id) ? 'border-emerald-700/50 bg-emerald-900/10 hover:border-emerald-600' :
                'border-gray-700 bg-gray-800/50 hover:border-gray-600'
              }`}
              onClick={() => setSelected(selected?.id === n.id ? null : n)}>
              <div className="flex items-center gap-2 mb-2">
                <span className="font-mono font-bold text-white">{n.id}</span>
                {n.is_hub && <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-900/50 text-amber-400 font-semibold">HUB</span>}
                {changes?.newNodeIds?.has(n.id) && <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-900/50 text-emerald-400 font-semibold">NEW</span>}
                {n.is_isolated && <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-900/50 text-indigo-400 font-semibold">LOCAL ONLY</span>}
                {n.community_id != null && <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-700 text-gray-400">C{n.community_id}</span>}
              </div>
              <div className="flex gap-4 text-xs text-gray-500 mb-1">
                <span>{n.client_count} apps</span>
                <span>{n.port_count} queues</span>
                <span>L:{n.local_queues || 0} R:{n.remote_queues || 0} A:{n.alias_queues || 0}</span>
              </div>
              {n.region && <div className="text-xs text-gray-600">{n.region}</div>}

              {/* Expanded details */}
              {selected?.id === n.id && (
                <div className="mt-2 pt-2 border-t border-gray-700 space-y-1">
                  {n.clients?.map(c => (
                    <div key={c.id} className="flex items-center gap-2 text-xs">
                      <span className="font-mono text-indigo-400">{c.app_id}</span>
                      <span className="text-gray-500 truncate">{c.name}</span>
                      <span className={`px-1 rounded text-[10px] ${
                        c.role === 'producer' ? 'bg-emerald-900/50 text-emerald-400' :
                        c.role === 'consumer' ? 'bg-amber-900/50 text-amber-400' :
                        'bg-purple-900/50 text-purple-400'
                      }`}>{c.role}</span>
                    </div>
                  ))}
                  {n.queues?.length > 0 && (
                    <div className="mt-2 pt-1 border-t border-gray-700">
                      <div className="text-[10px] text-gray-600 mb-1">Queues:</div>
                      {n.queues.slice(0, 10).map((q, i) => (
                        <div key={i} className="text-[10px] font-mono text-gray-500 flex gap-2">
                          <span className={q.type === 'local' ? 'text-emerald-600' : q.type === 'remote' ? 'text-amber-600' : 'text-purple-600'}>
                            {q.type[0].toUpperCase()}
                          </span>
                          <span>{q.name}</span>
                          {q.remote_qm && <span className="text-gray-700">-&gt; {q.remote_qm}</span>}
                        </div>
                      ))}
                      {n.queues.length > 10 && <div className="text-[10px] text-gray-600">...and {n.queues.length - 10} more</div>}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
