const BASE = '/api';

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Request failed');
  }
  return res;
}

export async function uploadCSV(file) {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${BASE}/upload`, { method: 'POST', body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Upload failed');
  }
  return res.json();
}

export async function runOptimization(resolution = 1.0) {
  const res = await request('/optimize', {
    method: 'POST',
    body: JSON.stringify({ resolution }),
  });
  return res.json();
}

export async function getAsIsTopology() {
  const res = await request('/topology/as-is');
  return res.json();
}

export async function getTargetTopology() {
  const res = await request('/topology/target');
  return res.json();
}

export async function getMetrics() {
  const res = await request('/metrics');
  return res.json();
}

export async function getDecisions(stage = null, limit = 100, offset = 0) {
  const params = new URLSearchParams({ limit, offset });
  if (stage) params.set('stage', stage);
  const res = await request(`/decisions?${params}`);
  return res.json();
}

export async function onboardApp(data) {
  const res = await request('/onboard', {
    method: 'POST',
    body: JSON.stringify(data),
  });
  return res.json();
}

export async function applyOnboard(appId, optionIndex) {
  const res = await request('/onboard/apply', {
    method: 'POST',
    body: JSON.stringify({ app_id: appId, option_index: optionIndex }),
  });
  return res.json();
}

export async function sendChat(message, useLLM = false) {
  const res = await request('/chat', {
    method: 'POST',
    body: JSON.stringify({ message, use_llm: useLLM }),
  });
  return res.json();
}

export function downloadCSV() {
  window.open(`${BASE}/export/csv`, '_blank');
}

export function downloadMQSC() {
  window.open(`${BASE}/export/mqsc`, '_blank');
}

export function downloadReport() {
  window.open(`${BASE}/export/report`, '_blank');
}
