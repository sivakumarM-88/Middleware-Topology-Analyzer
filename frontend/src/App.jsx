import { useState, useCallback } from 'react';
import Overview from './components/Overview';
import TopologyExplorer from './components/TopologyExplorer';
import OnboardApp from './components/OnboardApp';
import Chat from './components/Chat';
import { uploadCSV, runOptimization, getMetrics, getAsIsTopology, getTargetTopology, getDecisions, downloadCSV, downloadMQSC, downloadReport } from './utils/api';

const TABS = ['Overview', 'Topology Explorer', 'Onboard App', 'Chat'];

export default function App() {
  const [tab, setTab] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [optimized, setOptimized] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [optimizing, setOptimizing] = useState(false);
  const [error, setError] = useState(null);

  // Data
  const [uploadResult, setUploadResult] = useState(null);
  const [optResult, setOptResult] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [asIsGraph, setAsIsGraph] = useState(null);
  const [targetGraph, setTargetGraph] = useState(null);
  const [decisions, setDecisions] = useState([]);

  const handleUpload = useCallback(async (file) => {
    setError(null);
    setUploading(true);
    try {
      const res = await uploadCSV(file);
      setUploadResult(res);
      setLoaded(true);
      setOptimized(false);
      setOptResult(null);
      setTargetGraph(null);

      const [m, g] = await Promise.all([getMetrics(), getAsIsTopology()]);
      setMetrics(m);
      setAsIsGraph(g);
    } catch (e) {
      setError(e.message);
    } finally {
      setUploading(false);
    }
  }, []);

  const handleOptimize = useCallback(async () => {
    setError(null);
    setOptimizing(true);
    try {
      const res = await runOptimization();
      setOptResult(res);
      setOptimized(true);

      const [m, asIs, target, d] = await Promise.all([
        getMetrics(),
        getAsIsTopology(),
        getTargetTopology(),
        getDecisions(),
      ]);
      setMetrics(m);
      setAsIsGraph(asIs);
      setTargetGraph(target);
      setDecisions(d.decisions || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setOptimizing(false);
    }
  }, []);

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      {/* Header */}
      <header className="border-b border-gray-800 bg-gray-900/80 backdrop-blur-sm sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-indigo-600 rounded-lg flex items-center justify-center text-white font-bold text-sm">
              TQ
            </div>
            <h1 className="text-lg font-semibold text-white">TopologyIQ</h1>
            <span className="text-xs text-gray-500 hidden sm:inline">Graph intelligence for middleware topology</span>
          </div>
          <div className="flex items-center gap-2">
            {!loaded && (
              <label className={`px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm rounded-lg cursor-pointer transition ${uploading ? 'opacity-50 pointer-events-none' : ''}`}>
                {uploading ? 'Uploading...' : 'Upload CSV'}
                <input
                  type="file"
                  accept=".csv"
                  className="hidden"
                  onChange={(e) => e.target.files[0] && handleUpload(e.target.files[0])}
                  disabled={uploading}
                />
              </label>
            )}
            {loaded && !optimized && (
              <>
                <label className="px-3 py-2 bg-gray-700 hover:bg-gray-600 text-sm rounded-lg cursor-pointer transition">
                  Re-upload
                  <input
                    type="file"
                    accept=".csv"
                    className="hidden"
                    onChange={(e) => e.target.files[0] && handleUpload(e.target.files[0])}
                  />
                </label>
                <button
                  onClick={handleOptimize}
                  disabled={optimizing}
                  className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-sm rounded-lg transition disabled:opacity-50"
                >
                  {optimizing ? 'Optimizing...' : 'Run Optimizer'}
                </button>
              </>
            )}
            {optimized && (
              <>
                <label className="px-3 py-2 bg-gray-700 hover:bg-gray-600 text-sm rounded-lg cursor-pointer transition">
                  Re-upload
                  <input
                    type="file"
                    accept=".csv"
                    className="hidden"
                    onChange={(e) => e.target.files[0] && handleUpload(e.target.files[0])}
                  />
                </label>
                <button onClick={downloadCSV} className="px-3 py-2 bg-gray-700 hover:bg-gray-600 text-sm rounded-lg transition">
                  Export CSV
                </button>
                <button onClick={downloadMQSC} className="px-3 py-2 bg-gray-700 hover:bg-gray-600 text-sm rounded-lg transition">
                  MQSC
                </button>
                <button onClick={downloadReport} className="px-3 py-2 bg-gray-700 hover:bg-gray-600 text-sm rounded-lg transition">
                  Report
                </button>
              </>
            )}
          </div>
        </div>
      </header>

      {error && (
        <div className="max-w-7xl mx-auto px-4 pt-3">
          <div className="bg-red-900/50 border border-red-700 text-red-200 px-4 py-2 rounded-lg text-sm">
            {error}
            <button onClick={() => setError(null)} className="ml-2 text-red-400 hover:text-red-300">dismiss</button>
          </div>
        </div>
      )}

      {/* Landing */}
      {!loaded && !uploading && (
        <div className="flex flex-col items-center justify-center min-h-[70vh] gap-6 px-4">
          <div className="w-20 h-20 bg-indigo-600/20 border border-indigo-500/30 rounded-2xl flex items-center justify-center">
            <span className="text-4xl font-bold text-indigo-400">TQ</span>
          </div>
          <h2 className="text-3xl font-bold text-white">TopologyIQ</h2>
          <p className="text-gray-400 text-center max-w-md">
            Graph intelligence for middleware topology optimization.
            Upload your IBM MQ topology CSV to get started.
          </p>
          <label className="px-6 py-3 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg cursor-pointer transition text-lg">
            Upload CSV File
            <input
              type="file"
              accept=".csv"
              className="hidden"
              onChange={(e) => e.target.files[0] && handleUpload(e.target.files[0])}
            />
          </label>
          <div className="grid grid-cols-3 gap-8 mt-8 text-center max-w-lg">
            <div>
              <div className="text-2xl font-bold text-emerald-400">1</div>
              <div className="text-sm text-gray-500 mt-1">Upload</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-emerald-400">2</div>
              <div className="text-sm text-gray-500 mt-1">Optimize</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-emerald-400">3</div>
              <div className="text-sm text-gray-500 mt-1">Export</div>
            </div>
          </div>
        </div>
      )}

      {/* Tabs */}
      {loaded && (
        <>
          <nav className="border-b border-gray-800 bg-gray-900/50">
            <div className="max-w-7xl mx-auto px-4 flex gap-1">
              {TABS.map((t, i) => (
                <button
                  key={t}
                  onClick={() => setTab(i)}
                  className={`px-4 py-3 text-sm font-medium transition border-b-2 ${
                    tab === i
                      ? 'border-indigo-500 text-indigo-400'
                      : 'border-transparent text-gray-500 hover:text-gray-300'
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
          </nav>

          <main className="max-w-7xl mx-auto px-4 py-6">
            {tab === 0 && (
              <Overview
                uploadResult={uploadResult}
                optResult={optResult}
                metrics={metrics}
                decisions={decisions}
                optimized={optimized}
              />
            )}
            {tab === 1 && (
              <TopologyExplorer
                asIsGraph={asIsGraph}
                targetGraph={targetGraph}
                optimized={optimized}
                metrics={metrics}
                decisions={decisions}
              />
            )}
            {tab === 2 && <OnboardApp optimized={optimized} />}
            {tab === 3 && <Chat />}
          </main>
        </>
      )}
    </div>
  );
}
