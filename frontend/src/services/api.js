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

async function request(path, { method = 'GET', body } = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const detail = typeof data.detail === 'string' ? data.detail : `Request failed (${res.status})`;
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return res.status === 204 ? null : res.json();
}

/** Health probe that also measures round-trip latency. */
export async function probeHealth() {
  const started = performance.now();
  try {
    const data = await request('/api/health');
    return { ok: data?.status === 'ok', ms: Math.round(performance.now() - started) };
  } catch {
    return { ok: false, ms: Math.round(performance.now() - started) };
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

export const securityScan = (url) => request('/api/security/scan', { method: 'POST', body: { url } });

/** Retest takes the Finding fields only (strip UI/remediation extras). */
export function securityRetest(finding) {
  const { key, remediation, ...core } = finding; // eslint-disable-line no-unused-vars
  return request('/api/security/retest', { method: 'POST', body: core });
}
