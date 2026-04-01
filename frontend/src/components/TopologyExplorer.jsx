import { useState, useMemo } from 'react';
import ForceGraph from './ForceGraph';

/**
 * Filter a graph to show only nodes matching the filter and their direct
 * neighbors (nodes connected by an edge).  Links are kept only when both
 * endpoints survive the filter.
 */
function filterGraph(graph, filterQM, filterAppID) {
  if (!graph || (!filterQM && !filterAppID)) return graph;

  // Identify "seed" node IDs that match the filter criteria
  const seeds = new Set();
  for (const n of graph.nodes) {
    const matchQM = !filterQM || n.id === filterQM;
    const matchApp =
      !filterAppID ||
      (n.clients && n.clients.some((c) => c.app_id === filterAppID));
    if (matchQM && matchApp) seeds.add(n.id);
  }

  // Expand seeds to include their direct neighbors (one hop)
  const visible = new Set(seeds);
  for (const l of graph.links) {
    const src = typeof l.source === 'object' ? l.source.id : l.source;
    const tgt = typeof l.target === 'object' ? l.target.id : l.target;
    if (seeds.has(src)) visible.add(tgt);
    if (seeds.has(tgt)) visible.add(src);
  }

  const nodes = graph.nodes.filter((n) => visible.has(n.id));
  const nodeSet = new Set(nodes.map((n) => n.id));
  const links = graph.links.filter((l) => {
    const src = typeof l.source === 'object' ? l.source.id : l.source;
    const tgt = typeof l.target === 'object' ? l.target.id : l.target;
    return nodeSet.has(src) && nodeSet.has(tgt);
  });

  return { ...graph, nodes, links, summary: { ...graph.summary, total_nodes: nodes.length, total_edges: links.length } };
}

export default function TopologyExplorer({ asIsGraph, targetGraph, optimized }) {
  const [selected, setSelected] = useState(null);
  const [view, setView] = useState('side-by-side'); // 'side-by-side' | 'as-is' | 'target'
  const [filterQM, setFilterQM] = useState('');
  const [filterAppID, setFilterAppID] = useState('');

  // Build dropdown options from the active data source
  // (all hooks must run before any conditional return)
  const activeRaw = view === 'target' && targetGraph ? targetGraph : asIsGraph;
  const qmOptions = useMemo(() => {
    if (!activeRaw) return [];
    return [...new Set(activeRaw.nodes.map((n) => n.id))].sort();
  }, [activeRaw]);

  const appOptions = useMemo(() => {
    if (!activeRaw) return [];
    const ids = new Set();
    for (const n of activeRaw.nodes) {
      if (n.clients) n.clients.forEach((c) => ids.add(c.app_id));
    }
    return [...ids].sort();
  }, [activeRaw]);

  // Apply filters
  const hasFilter = filterQM || filterAppID;
  const filteredAsIs = useMemo(
    () => filterGraph(asIsGraph, filterQM, filterAppID),
    [asIsGraph, filterQM, filterAppID],
  );
  const filteredTarget = useMemo(
    () => filterGraph(targetGraph, filterQM, filterAppID),
    [targetGraph, filterQM, filterAppID],
  );

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
      {/* Filter & View controls */}
      <div className="flex flex-wrap items-end gap-4 mb-4">
        {/* QM filter */}
        <div className="flex flex-col gap-1">
          <label className="text-[10px] text-gray-500 uppercase tracking-wider">Queue Manager</label>
          <select
            value={filterQM}
            onChange={(e) => setFilterQM(e.target.value)}
            className="bg-gray-800 border border-gray-700 text-gray-200 text-xs rounded-lg px-2 py-1.5 min-w-[160px] focus:border-indigo-500 focus:outline-none"
          >
            <option value="">All QMs ({qmOptions.length})</option>
            {qmOptions.map((qm) => (
              <option key={qm} value={qm}>{qm}</option>
            ))}
          </select>
        </div>

        {/* AppID filter */}
        <div className="flex flex-col gap-1">
          <label className="text-[10px] text-gray-500 uppercase tracking-wider">Application ID</label>
          <select
            value={filterAppID}
            onChange={(e) => setFilterAppID(e.target.value)}
            className="bg-gray-800 border border-gray-700 text-gray-200 text-xs rounded-lg px-2 py-1.5 min-w-[160px] focus:border-indigo-500 focus:outline-none"
          >
            <option value="">All Apps ({appOptions.length})</option>
            {appOptions.map((id) => (
              <option key={id} value={id}>{id}</option>
            ))}
          </select>
        </div>

        {/* Clear filters */}
        {hasFilter && (
          <button
            onClick={() => { setFilterQM(''); setFilterAppID(''); }}
            className="px-3 py-1.5 text-xs rounded-lg bg-red-900/40 text-red-300 hover:bg-red-900/60 transition"
          >
            Clear filters
          </button>
        )}

        {/* Spacer */}
        <div className="flex-1" />

        {/* View toggle */}
        {optimized && targetGraph && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500 mr-1">View:</span>
            {['side-by-side', 'as-is', 'target'].map((v) => (
              <button
                key={v}
                onClick={() => setView(v)}
                className={`px-3 py-1.5 text-xs rounded-lg transition ${
                  view === v
                    ? 'bg-indigo-600 text-white'
                    : 'bg-gray-800 text-gray-400 hover:text-gray-200'
                }`}
              >
                {v === 'side-by-side' ? 'Side by Side' : v === 'as-is' ? 'As-Is Only' : 'Target Only'}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Filter info banner */}
      {hasFilter && graphData && (
        <div className="mb-3 px-3 py-2 rounded-lg bg-indigo-900/20 border border-indigo-800 text-xs text-indigo-300">
          Showing {graphData.nodes.length} QMs and {graphData.links.length} channels
          {filterQM && <> matching QM <span className="font-mono font-bold">{filterQM}</span></>}
          {filterQM && filterAppID && <> and</>}
          {filterAppID && <> App <span className="font-mono font-bold">{filterAppID}</span></>}
          {' '}(+ direct neighbors)
        </div>
      )}

      {/* Graph views */}
      {showSideBySide ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <ForceGraph
            data={filteredAsIs}
            width={600}
            height={500}
            title="As-Is Topology (before optimization)"
            onSelectNode={setSelected}
          />
          <ForceGraph
            data={filteredTarget}
            width={600}
            height={500}
            title="Target Topology (optimized)"
            onSelectNode={setSelected}
          />
        </div>
      ) : (
        <ForceGraph
          data={graphData || filteredAsIs}
          width={1100}
          height={600}
          title={view === 'target' ? 'Target Topology (optimized)' : 'As-Is Topology'}
          onSelectNode={setSelected}
        />
      )}

      {/* Legend */}
      <div className="mt-4 p-3 bg-gray-900/50 border border-gray-800 rounded-xl">
        <div className="flex flex-wrap gap-x-6 gap-y-2 text-xs text-gray-400">
          <span className="text-gray-500 font-medium">Legend:</span>
          <div className="flex items-center gap-1.5">
            <div className="w-3 h-3 rounded-full border-2 border-amber-400" />
            <span>Hub QM (dashed ring)</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-3 h-3 rounded-full bg-indigo-500/30 border border-indigo-500" />
            <span>Standard QM</span>
          </div>
          <div className="flex items-center gap-1.5">
            <svg width="24" height="8"><line x1="0" y1="4" x2="24" y2="4" stroke="#6366f1" strokeWidth="1.5" /></svg>
            <span>Channel</span>
          </div>
          <div className="flex items-center gap-1.5">
            <svg width="24" height="8"><line x1="0" y1="4" x2="24" y2="4" stroke="#6366f1" strokeWidth="2" strokeDasharray="4,3" /></svg>
            <span>Backbone (hub-to-hub)</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-4 h-4 rounded-full bg-gray-800 border border-gray-600 flex items-center justify-center text-[8px] font-bold text-gray-300">5</div>
            <span>Queue count badge</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-gray-500">C0, C1...</span>
            <span>Community ID</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-gray-300">P</span>
            <span>Producer</span>
            <span className="font-mono text-gray-300 ml-1">C</span>
            <span>Consumer</span>
            <span className="font-mono text-gray-300 ml-1">B</span>
            <span>Both</span>
          </div>
        </div>
      </div>

      {/* Channel list */}
      {displayData && displayData.links && displayData.links.length > 0 && (
        <div className="mt-4 bg-gray-900/50 border border-gray-800 rounded-xl p-4">
          <h3 className="text-sm font-medium text-gray-300 mb-3">
            Channels ({displayData.links.length})
            {displayData.links.length > 200 && (
              <span className="text-gray-500 font-normal ml-2">(showing first 200)</span>
            )}
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
                {displayData.links.slice(0, 200).map((l) => (
                  <tr key={l.id} className="border-t border-gray-800">
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
                    <td className="px-3 py-2 text-gray-500">{(l.flows || []).join(', ') || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Node details grid */}
      <div className="mt-4 bg-gray-900/50 border border-gray-800 rounded-xl p-4">
        <h3 className="text-sm font-medium text-gray-300 mb-3">
          Queue Managers ({displayData.nodes.length})
          {displayData.nodes.length > 100 && !hasFilter && (
            <span className="text-gray-500 font-normal ml-2">(use filters above to narrow results)</span>
          )}
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 max-h-[600px] overflow-y-auto">
          {displayData.nodes.map((n) => (
            <div
              key={n.id}
              className={`p-3 rounded-lg border transition cursor-pointer ${
                selected?.id === n.id
                  ? 'border-indigo-500 bg-indigo-900/20'
                  : 'border-gray-700 bg-gray-800/50 hover:border-gray-600'
              }`}
              onClick={() => setSelected(selected?.id === n.id ? null : n)}
            >
              <div className="flex items-center gap-2 mb-2">
                <span className="font-mono font-bold text-white">{n.id}</span>
                {n.is_hub && <span className="text-xs px-1.5 py-0.5 rounded bg-amber-900/50 text-amber-400 font-semibold">HUB</span>}
                {n.community_id != null && (
                  <span className="text-xs px-1.5 py-0.5 rounded bg-gray-700 text-gray-400">C{n.community_id}</span>
                )}
              </div>
              <div className="flex gap-4 text-xs text-gray-500 mb-2">
                <span>{n.client_count} apps</span>
                <span>{n.port_count} queues</span>
                <span>L:{n.local_queues || 0} R:{n.remote_queues || 0} A:{n.alias_queues || 0}</span>
              </div>
              {n.region && <div className="text-xs text-gray-600">{n.region}</div>}

              {/* Expand on select */}
              {selected?.id === n.id && (
                <div className="mt-2 pt-2 border-t border-gray-700 space-y-1">
                  {n.clients && n.clients.map((c) => (
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
                  {n.queues && n.queues.length > 0 && (
                    <div className="mt-2 pt-1 border-t border-gray-700">
                      <div className="text-[10px] text-gray-600 mb-1">Queues:</div>
                      {n.queues.slice(0, 10).map((q, i) => (
                        <div key={i} className="text-[10px] font-mono text-gray-500 flex gap-2">
                          <span className={
                            q.type === 'local' ? 'text-emerald-600' :
                            q.type === 'remote' ? 'text-amber-600' : 'text-purple-600'
                          }>{q.type[0].toUpperCase()}</span>
                          <span>{q.name}</span>
                          {q.remote_qm && <span className="text-gray-700">-&gt; {q.remote_qm}</span>}
                        </div>
                      ))}
                      {n.queues.length > 10 && (
                        <div className="text-[10px] text-gray-600">...and {n.queues.length - 10} more</div>
                      )}
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
