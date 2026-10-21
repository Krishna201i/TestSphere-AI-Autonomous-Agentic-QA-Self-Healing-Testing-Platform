/**
 * TestSphere-AI — API client for the FastAPI backend.
 *
 * Base URL: VITE_API_URL when set; same-origin when served by Vite (proxy,
 * port 3000) or by the backend itself (port 8000); otherwise 127.0.0.1:8000.
 */

function getApiBase() {
  if (import.meta.env.VITE_API_URL) return import.meta.env.VITE_API_URL.replace(/\/$/, '');
  if (typeof window !== 'undefined' && ['3000', '8000'].includes(window.location.port)) return '';
  return 'http://127.0.0.1:8000';
}

const BASE_URL = getApiBase();

/** Where the dashboard sends API calls, for display ("same origin" when proxied). */
export const API_BASE_LABEL = BASE_URL || (typeof window !== 'undefined' ? `${window.location.origin} (same origin)` : 'same origin');

/**
 * Fetch JSON from the backend.  Errors carry a `kind` the UI can explain:
 *   network  — backend unreachable
 *   outdated — endpoint missing (backend runs older code than the dashboard)
 *   refused  — 403 (e.g. target outside the authorized scope)
 *   http     — anything else; `message` is the server's detail
 */
async function request(path, { method = 'GET', body } = {}) {
  let res;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    const err = new Error(`Cannot reach the backend at ${API_BASE_LABEL}. Is it running?`);
    err.kind = 'network';
    throw err;
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    let detail = typeof data.detail === 'string' ? data.detail : `Request failed (${res.status})`;
    let kind = res.status === 403 ? 'refused' : 'http';
    if (res.status === 404 && (data.detail === 'Not Found' || !data.detail)) {
      kind = 'outdated';
      detail = `The backend at ${API_BASE_LABEL} has no ${path.split('?')[0]} endpoint — it is running an older version. Deploy or restart it with the latest code.`;
    }
    const err = new Error(detail);
    err.status = res.status;
    err.kind = kind;
    throw err;
  }
  return res.status === 204 ? null : res.json();
}

/** Health probe that also measures round-trip latency. */
export async function probeHealth() {
  const started = performance.now();
  try {
    const data = await request('/api/health');
    // "degraded" = API up but its database is down
    return {
      ok: data?.status === 'ok' || data?.status === 'degraded',
      db: data?.database || 'ok',
      dbError: data?.database_error || null,
      ms: Math.round(performance.now() - started),
    };
  } catch {
    return { ok: false, db: 'unknown', dbError: null, ms: Math.round(performance.now() - started) };
  }
}

export const getProjects = () => request('/api/projects');
export const createProject = (payload) => request('/api/projects', { method: 'POST', body: payload });
export const getApplications = () => request('/api/applications');
export const createApplication = (payload) => request('/api/applications', { method: 'POST', body: payload });
export const getTestCases = () => request('/api/test-cases');
export const getTestExecutions = () => request('/api/test-executions');

export const planAndExecute = (payload) =>
  request('/api/workflow/plan-and-execute', { method: 'POST', body: payload });

export const securityScan = (url, actor) => request('/api/security/scan', { method: 'POST', body: { url, actor } });
export const getFindings = () => request('/api/security/findings');
export const approveFinding = (key, actor) =>
  request(`/api/security/findings/${encodeURIComponent(key)}/approve`, { method: 'POST', body: { actor } });
export const retestFinding = (key, actor) =>
  request(`/api/security/findings/${encodeURIComponent(key)}/retest`, { method: 'POST', body: { actor } });
export const getAudit = (limit = 300) => request(`/api/audit?limit=${limit}`);
export const getSystem = () => request('/api/system');
export const ingestCodebase = (source, actor) => request('/api/ingest', { method: 'POST', body: { source, actor } });
export const listBlueprints = () => request('/api/ingest');
export const getBlueprint = (id) => request(`/api/ingest/${id}`);
