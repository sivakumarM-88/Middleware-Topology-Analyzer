import { useState } from 'react';
import { onboardApp, applyOnboard } from '../utils/api';

export default function OnboardApp({ optimized }) {
  const [form, setForm] = useState({
    app_id: '',
    app_name: '',
    role: 'producer',
    target_app_id: '',
    neighborhood: '',
    pci: false,
    trtc: '',
  });
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [applied, setApplied] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    setResult(null);
    setApplied(false);
    try {
      const res = await onboardApp(form);
      setResult(res);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleApply = async (index) => {
    try {
      await applyOnboard(result.app_id, index);
      setApplied(true);
    } catch (err) {
      setError(err.message);
    }
  };

  if (!optimized) {
    return (
      <div className="text-center py-12 text-gray-500">
        <p>Run the optimizer first before onboarding new applications.</p>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto">
      <h2 className="text-lg font-semibold text-white mb-4">Onboard New Application</h2>

      <form onSubmit={handleSubmit} className="bg-gray-900/50 border border-gray-800 rounded-xl p-6 space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs text-gray-400 mb-1">App ID</label>
            <input
              type="text"
              required
              value={form.app_id}
              onChange={(e) => setForm({ ...form, app_id: e.target.value })}
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:border-indigo-500 focus:outline-none"
              placeholder="e.g., RSKENG"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">App Name</label>
            <input
              type="text"
              required
              value={form.app_name}
              onChange={(e) => setForm({ ...form, app_name: e.target.value })}
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:border-indigo-500 focus:outline-none"
              placeholder="e.g., Risk Engine"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Role</label>
            <select
              value={form.role}
              onChange={(e) => setForm({ ...form, role: e.target.value })}
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:border-indigo-500 focus:outline-none"
            >
              <option value="producer">Producer</option>
              <option value="consumer">Consumer</option>
              <option value="both">Both</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Connect to App (Target App ID)</label>
            <input
              type="text"
              required
              value={form.target_app_id}
              onChange={(e) => setForm({ ...form, target_app_id: e.target.value })}
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:border-indigo-500 focus:outline-none"
              placeholder="e.g., PPCSM"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Neighborhood</label>
            <input
              type="text"
              value={form.neighborhood}
              onChange={(e) => setForm({ ...form, neighborhood: e.target.value })}
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:border-indigo-500 focus:outline-none"
              placeholder="e.g., Wholesale Banking"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">TRTC</label>
            <select
              value={form.trtc}
              onChange={(e) => setForm({ ...form, trtc: e.target.value })}
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:border-indigo-500 focus:outline-none"
            >
              <option value="">Select...</option>
              <option value="00= 0-30 Minutes">0-30 Minutes</option>
              <option value="02= 2 Hours to 4 Hours">2-4 Hours</option>
              <option value="03= 4:01 to 11:59 Hours">4-12 Hours</option>
            </select>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={form.pci}
            onChange={(e) => setForm({ ...form, pci: e.target.checked })}
            className="rounded bg-gray-800 border-gray-700"
            id="pci"
          />
          <label htmlFor="pci" className="text-sm text-gray-400">PCI Compliant</label>
        </div>

        {error && <p className="text-sm text-red-400">{error}</p>}

        <button
          type="submit"
          disabled={loading}
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm transition disabled:opacity-50"
        >
          {loading ? 'Analyzing...' : 'Get Placement Recommendations'}
        </button>
      </form>

      {/* Results */}
      {result && (
        <div className="mt-6 space-y-4">
          <h3 className="text-sm font-medium text-gray-300">
            Placement Options for {result.app_name} ({result.app_id})
          </h3>

          {result.options.map((opt, i) => (
            <div
              key={i}
              className={`p-4 rounded-xl border ${
                i === result.recommended_option
                  ? 'border-emerald-600/50 bg-emerald-900/10'
                  : 'border-gray-800 bg-gray-900/50'
              }`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="font-mono font-bold text-white">{opt.qm_id}</span>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    opt.strategy === 'same_qm' ? 'bg-emerald-900/50 text-emerald-300' :
                    opt.strategy === 'same_community' ? 'bg-blue-900/50 text-blue-300' :
                    'bg-amber-900/50 text-amber-300'
                  }`}>{opt.strategy.replace('_', ' ')}</span>
                  {i === result.recommended_option && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-600 text-white">Recommended</span>
                  )}
                </div>
                <span className={`text-sm font-mono ${opt.complexity_delta <= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {opt.complexity_delta >= 0 ? '+' : ''}{opt.complexity_delta.toFixed(1)} complexity
                </span>
              </div>

              <p className="text-sm text-gray-400 mt-2">{opt.reasoning}</p>

              {opt.mqsc_commands.length > 0 && (
                <div className="mt-3 bg-gray-950 rounded-lg p-3">
                  <div className="text-xs text-gray-500 mb-1">MQSC Commands:</div>
                  <pre className="text-xs text-green-400 overflow-x-auto">
                    {opt.mqsc_commands.join('\n')}
                  </pre>
                </div>
              )}

              {!applied && (
                <button
                  onClick={() => handleApply(i)}
                  className="mt-3 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white text-xs rounded-lg transition"
                >
                  Apply This Option
                </button>
              )}
            </div>
          ))}

          {applied && (
            <div className="p-4 bg-emerald-900/20 border border-emerald-700/50 rounded-xl text-emerald-300 text-sm">
              Application placed successfully. The topology has been updated.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
