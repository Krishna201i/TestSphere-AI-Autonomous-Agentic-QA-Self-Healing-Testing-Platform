// A hosted dashboard: default HTTPS port, like the EC2 server (jsdom's default is localhost:3000)
// @vitest-environment-options {"url": "https://54-153-148-247.sslip.io/"}
import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.resetModules();
});

async function baseLabelOn(url, env = {}) {
  for (const [k, v] of Object.entries(env)) vi.stubEnv(k, v);
  window.history.replaceState(null, '', url);
  const calls = [];
  vi.stubGlobal('fetch', vi.fn(async (input) => {
    calls.push(String(input));
    return new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  }));
  const api = await import('../services/api');
  await api.getProjects();
  return calls[0];
}

describe('API base URL', () => {
  it('uses the page origin when VITE_API_URL is unset, on any port', async () => {
    // Regression: on the default HTTPS port (a hosted server) requests went to 127.0.0.1:8000
    expect(await baseLabelOn('/')).toBe('/api/projects');
  });

  it('uses VITE_API_URL when the dashboard is hosted apart from the API', async () => {
    const url = await baseLabelOn('/', { VITE_API_URL: 'https://api.example.org/' });
    expect(url).toBe('https://api.example.org/api/projects');
  });

  it('asks only for recent executions and the totals separately', async () => {
    window.history.replaceState(null, '', '/');
    const calls = [];
    vi.stubGlobal('fetch', vi.fn(async (input) => {
      calls.push(String(input));
      return new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } });
    }));
    const api = await import('../services/api');
    await api.getTestExecutions();
    await api.getExecutionStats();
    expect(calls).toEqual([`/api/test-executions?limit=${api.RECENT_EXECUTIONS}`, '/api/test-executions/stats']);
  });
});

describe('A dashboard host answering instead of the API', () => {
  it('explains that VITE_API_URL is missing, not a JSON parse error', async () => {
    window.history.replaceState(null, '', '/');
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<!doctype html><div id="root"></div>', {
      status: 200, headers: { 'Content-Type': 'text/html; charset=utf-8' },
    })));
    const api = await import('../services/api');
    const err = await api.getSystem().catch((e) => e);
    expect(err.kind).toBe('misconfigured');
    expect(err.message).toContain('VITE_API_URL');
  });
});
