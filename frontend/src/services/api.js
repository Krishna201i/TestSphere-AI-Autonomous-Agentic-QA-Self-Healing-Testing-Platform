/**
 * TestSphere-AI — API client for the FastAPI backend.
 *
 * Base URL: VITE_API_URL when set (a dashboard hosted apart from the API,
 * e.g. on Vercel); otherwise the page's own origin: the backend serves the
 * built dashboard itself, and the Vite dev server proxies /api.  (Guessing
 * from the port broke hosted pages: on Render the port is the default 443,
 * so the dashboard called http://127.0.0.1:8000 on the visitor's machine.)
 */

function getApiBase() {
  if (import.meta.env.VITE_API_URL) return import.meta.env.VITE_API_URL.replace(/\/$/, '');
  return '';
}

const BASE_URL = getApiBase();

/** Where the dashboard sends API calls, for display ("same origin" when proxied). */
export const API_BASE_LABEL = BASE_URL || (typeof window !== 'undefined' ? `${window.location.origin} (same origin)` : 'same origin');

// Set by the auth provider: returns a fresh Firebase ID token (or null when
// sign-in is off), and is told when the backend rejects the session.
let tokenProvider = async () => null;
let onUnauthorized = () => {};

export function configureAuth({ getToken, unauthorized }) {
  tokenProvider = getToken || (async () => null);
  onUnauthorized = unauthorized || (() => {});
}

/**
 * Fetch JSON from the backend.  Errors carry a `kind` the UI can explain:
 *   network  — backend unreachable
 *   auth     — 401, the session expired (the user is sent back to sign-in)
 *   outdated — endpoint missing (backend runs older code than the dashboard)
 *   refused  — 403 (e.g. target outside the authorized scope)
 *   http     — anything else; `message` is the server's detail
 */
async function request(path, { method = 'GET', body } = {}) {
  let res;
  const headers = {};
  if (body) headers['Content-Type'] = 'application/json';
  const token = await tokenProvider();
  if (token) headers.Authorization = `Bearer ${token}`;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      method,
      headers,
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
    let kind = res.status === 403 ? 'refused' : res.status === 401 ? 'auth' : 'http';
    if (res.status === 401 && token) onUnauthorized(detail);
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
// Only the newest `limit` executions (oldest first); totals come from getExecutionStats
export const getTestExecutions = (limit = RECENT_EXECUTIONS) => request(`/api/test-executions?limit=${limit}`);
export const getExecutionStats = () => request('/api/test-executions/stats');
export const RECENT_EXECUTIONS = 200;

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

export const updateProject = (id, payload) => request(`/api/projects/${id}`, { method: 'PUT', body: payload });
export const rotateWebhookSecret = (id) => request(`/api/projects/${id}/webhook-secret`, { method: 'POST' });
export const runProjectPipeline = (projectId, ingest = false) =>
  request('/api/pipelines/run', { method: 'POST', body: { project_id: projectId, ingest } });
export const quickPipeline = (payload) => request('/api/pipelines/quick', { method: 'POST', body: payload });
export const getPipelineRuns = (limit = 30) => request(`/api/pipelines/runs?limit=${limit}`);
export const getPipelineRun = (id) => request(`/api/pipelines/runs/${id}`);

export const getMe = () => request('/api/me');
export const recordLogin = () => request('/api/me/login', { method: 'POST' });
export const updateMe = (payload) => request('/api/me', { method: 'PUT', body: payload });
// Erases the account and all its data; `confirm` must be exactly "DELETE MY ACCOUNT"
export const deleteMe = (confirm) => request('/api/me', { method: 'DELETE', body: { confirm } });

/** Webhook URL GitHub should call for a project (absolute, using the API base). */
export const webhookUrl = (projectId) =>
  `${BASE_URL || (typeof window !== 'undefined' ? window.location.origin : '')}/api/webhooks/github/${projectId}`;
