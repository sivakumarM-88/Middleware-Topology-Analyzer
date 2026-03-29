import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts';

function MetricCard({ label, value, delta, color = 'indigo' }) {
  const colors = {
    indigo: 'bg-indigo-900/30 border-indigo-700/50',
    emerald: 'bg-emerald-900/30 border-emerald-700/50',
    amber: 'bg-amber-900/30 border-amber-700/50',
    rose: 'bg-rose-900/30 border-rose-700/50',
  };
  return (
    <div className={`rounded-xl border p-4 ${colors[color]}`}>
      <div className="text-xs text-gray-400 uppercase tracking-wider">{label}</div>
      <div className="text-2xl font-bold text-white mt-1">{value}</div>
      {delta != null && (
        <div className={`text-sm mt-1 ${delta >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
          {delta >= 0 ? '+' : ''}{delta}
        </div>
      )}
    </div>
  );
}

function WaterfallChart({ stages }) {
  if (!stages || stages.length === 0) return null;

  const data = stages.map((s) => ({
    name: s.stage_name.replace('Stage ', 'S'),
    delta: Math.round(s.complexity_delta * 10) / 10,
    before: Math.round(s.metrics_before.composite_score * 10) / 10,
    after: Math.round(s.metrics_after.composite_score * 10) / 10,
  }));

  return (
    <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4 mt-6">
      <h3 className="text-sm font-medium text-gray-300 mb-4">Complexity Waterfall (delta per stage)</h3>
      <ResponsiveContainer width="100%" height={250}>
        <BarChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis dataKey="name" tick={{ fill: '#9ca3af', fontSize: 11 }} />
          <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} />
          <Tooltip
            contentStyle={{ background: '#1f2937', border: '1px solid #374151', borderRadius: 8, color: '#f3f4f6' }}
            formatter={(value, name, props) => {
              const item = props.payload;
              return [`${item.before} → ${item.after} (Δ ${value >= 0 ? '+' : ''}${value})`, 'Score'];
            }}
          />
          <Bar dataKey="delta" radius={[4, 4, 0, 0]}>
            {data.map((entry, index) => (
              <Cell key={index} fill={entry.delta <= 0 ? '#10b981' : '#ef4444'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function DecisionList({ decisions }) {
  if (!decisions || decisions.length === 0) {
    return <p className="text-gray-500 text-sm">No decisions recorded yet.</p>;
  }

  const stageColors = {
    graph_discovery: 'bg-blue-900/50 text-blue-300',
    constraint_enforcement: 'bg-amber-900/50 text-amber-300',
    dead_object_pruning: 'bg-red-900/50 text-red-300',
    community_detection: 'bg-purple-900/50 text-purple-300',
    hub_election: 'bg-emerald-900/50 text-emerald-300',
    rationalization: 'bg-cyan-900/50 text-cyan-300',
    parsing: 'bg-gray-800 text-gray-300',
    onboarding: 'bg-indigo-900/50 text-indigo-300',
  };

  return (
    <div className="space-y-2 max-h-96 overflow-y-auto">
      {decisions.map((d, i) => (
        <div key={d.id || i} className="flex items-start gap-3 p-3 bg-gray-900/50 border border-gray-800 rounded-lg">
          <span className={`text-xs px-2 py-0.5 rounded-full whitespace-nowrap ${stageColors[d.stage] || 'bg-gray-800 text-gray-300'}`}>
            {d.stage}
          </span>
          <div className="flex-1 min-w-0">
            <p className="text-sm text-gray-200 break-words">{d.description}</p>
            {d.reason && <p className="text-xs text-gray-500 mt-1">{d.reason}</p>}
          </div>
          {d.complexity_delta !== 0 && (
            <span className={`text-xs font-mono whitespace-nowrap ${d.complexity_delta < 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {d.complexity_delta > 0 ? '+' : ''}{d.complexity_delta.toFixed(1)}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

export default function Overview({ uploadResult, optResult, metrics, decisions, optimized }) {
  const asIs = metrics?.as_is;
  const target = metrics?.target;

  return (
    <div>
      {/* Metric Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          label="Queue Managers"
          value={asIs?.total_nodes ?? '—'}
          delta={target ? target.total_nodes - asIs.total_nodes : null}
          color="indigo"
        />
        <MetricCard
          label="Channels"
          value={asIs?.total_edges ?? '—'}
          delta={target ? target.total_edges - asIs.total_edges : null}
          color="amber"
        />
        <MetricCard
          label="Applications"
          value={asIs?.total_clients ?? '—'}
          color="emerald"
        />
        <MetricCard
          label="Complexity Score"
          value={asIs?.composite_score?.toFixed(1) ?? '—'}
          delta={metrics?.reduction_pct != null ? `${metrics.reduction_pct}% reduction` : null}
          color={optimized ? 'emerald' : 'rose'}
        />
      </div>

      {/* Target metrics row */}
      {target && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
          <MetricCard label="Target QMs" value={target.total_nodes} color="emerald" />
          <MetricCard label="Target Channels" value={target.total_edges} color="emerald" />
          <MetricCard label="Target Queues" value={target.total_ports} color="emerald" />
          <MetricCard label="Target Score" value={target.composite_score.toFixed(1)} color="emerald" />
        </div>
      )}

      {/* Waterfall */}
      {metrics?.stages && <WaterfallChart stages={metrics.stages} />}

      {/* Parsed apps table */}
      {uploadResult?.clients && (
        <div className="mt-6 bg-gray-900/50 border border-gray-800 rounded-xl p-4">
          <h3 className="text-sm font-medium text-gray-300 mb-3">Applications ({uploadResult.clients.length})</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead className="text-xs text-gray-500 uppercase">
                <tr>
                  <th className="px-3 py-2">App ID</th>
                  <th className="px-3 py-2">Name</th>
                  <th className="px-3 py-2">Role</th>
                  <th className="px-3 py-2">Home QM</th>
                </tr>
              </thead>
              <tbody>
                {uploadResult.clients.map((c) => (
                  <tr key={c.id} className="border-t border-gray-800">
                    <td className="px-3 py-2 font-mono text-indigo-400">{c.app_id}</td>
                    <td className="px-3 py-2 text-gray-300">{c.name}</td>
                    <td className="px-3 py-2">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${
                        c.role === 'producer' ? 'bg-emerald-900/50 text-emerald-300' :
                        c.role === 'consumer' ? 'bg-amber-900/50 text-amber-300' :
                        'bg-purple-900/50 text-purple-300'
                      }`}>{c.role}</span>
                    </td>
                    <td className="px-3 py-2 font-mono text-gray-400">{c.home_qm}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Decision Log */}
      {decisions.length > 0 && (
        <div className="mt-6">
          <h3 className="text-sm font-medium text-gray-300 mb-3">Decision Log ({decisions.length})</h3>
          <DecisionList decisions={decisions} />
        </div>
      )}
    </div>
  );
}
