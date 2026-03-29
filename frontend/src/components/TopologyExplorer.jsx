import { useState } from 'react';
import ForceGraph from './ForceGraph';

export default function TopologyExplorer({ asIsGraph, targetGraph, optimized }) {
  const [selected, setSelected] = useState(null);
  const [view, setView] = useState('side-by-side'); // 'side-by-side' | 'as-is' | 'target'

  if (!asIsGraph) {
    return (
      <div className="text-center py-16 text-gray-500">
        <p className="text-lg">Upload a CSV to view the topology.</p>
      </div>
    );
  }

  const graphData = view === 'target' ? targetGraph : asIsGraph;
  const showSideBySide = view === 'side-by-side' && optimized && targetGraph;

  return (
    <div>
      {/* View controls */}
      {optimized && targetGraph && (
        <div className="flex items-center gap-2 mb-4">
          <span className="text-xs text-gray-500 mr-2">View:</span>
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

      {/* Graph views */}
      {showSideBySide ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <ForceGraph
            data={asIsGraph}
            width={600}
            height={500}
            title="As-Is Topology (before optimization)"
            onSelectNode={setSelected}
          />
          <ForceGraph
            data={targetGraph}
            width={600}
            height={500}
            title="Target Topology (optimized)"
            onSelectNode={setSelected}
          />
        </div>
      ) : (
        <ForceGraph
          data={graphData || asIsGraph}
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
      {graphData && graphData.links && graphData.links.length > 0 && (
        <div className="mt-4 bg-gray-900/50 border border-gray-800 rounded-xl p-4">
          <h3 className="text-sm font-medium text-gray-300 mb-3">
            Channels ({graphData.links.length})
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left">
              <thead className="text-gray-500 uppercase">
                <tr>
                  <th className="px-3 py-2">Channel Name</th>
                  <th className="px-3 py-2">From</th>
                  <th className="px-3 py-2">To</th>
                  <th className="px-3 py-2">Type</th>
                  <th className="px-3 py-2">Flows</th>
                </tr>
              </thead>
              <tbody>
                {graphData.links.map((l) => (
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
          Queue Managers ({(graphData || asIsGraph).nodes.length})
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {(graphData || asIsGraph).nodes.map((n) => (
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
