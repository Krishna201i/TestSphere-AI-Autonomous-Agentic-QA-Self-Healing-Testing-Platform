/**
 * Dashboard numbers, all derived from real workspace data (pipeline runs,
 * executions, findings, the audit trail).  Pure functions: tested in
 * __tests__/dashboard.test.js.
 */
import { toDate } from './derive';

const ACTIVE = ['queued', 'running'];
export const WINDOW = 10; // runs per comparison window

/** Finished runs, newest first. */
export function finishedRuns(runs) {
  return (runs || []).filter((r) => !ACTIVE.includes(r.status) && r.summary)
    .sort((a, b) => toDate(b.finished_at || b.created_at) - toDate(a.finished_at || a.created_at));
}

/** Share of a run's tests that passed (healed counts as passed), or null without tests. */
export function runPassRate(run) {
  const s = run?.summary;
  return s && s.total ? s.passed / s.total : null;
}

function poolRate(runs) {
  const total = runs.reduce((n, r) => n + (r.summary?.total || 0), 0);
  return total ? runs.reduce((n, r) => n + (r.summary?.passed || 0), 0) / total : null;
}

const sum = (runs, key) => runs.reduce((n, r) => n + (r.summary?.[key] || 0), 0);

/** Change from *before* to *now*: a relative % for counts, percentage points for rates. */
export function delta(now, before, { points = false } = {}) {
  if (now == null || before == null) return null;
  if (points) return (now - before) * 100;
  if (before === 0) return now === 0 ? 0 : null;
  return ((now - before) / before) * 100;
}

/** Self-healing success: of the runs where a locator broke, the share that healed instead of failing. */
export function healStats(list) {
  const executions = list || [];
  const healed = executions.filter((e) => e.status === 'HEALED').length;
  const failedHeal = executions.filter((e) => e.status === 'FAILED' && /self-healing tried|reviewer rejected healing/i.test(e.error_message || '')).length;
  const attempts = healed + failedHeal;
  return { healed, failedHeal, attempts, rate: attempts ? healed / attempts : null };
}

/** The four KPI tiles: value, trend (latest WINDOW runs vs the WINDOW before) and a sparkline series. */
export function kpis(ws) {
  const { pipelineRuns, executions, executionTotals } = ws;
  const findings = ws.findings || [];
  const runs = finishedRuns(pipelineRuns);
  const now = runs.slice(0, WINDOW);
  const before = runs.slice(WINDOW, WINDOW * 2);
  const series = (fn) => now.slice().reverse().map(fn).filter((v) => v != null);
  const openFindings = findings.filter((f) => (f.status || 'open') === 'open').length;
  const latest = runs[0];
  const heal = healStats(executions);
  // Heal success per run, where the run had any breakage
  const healSeries = series((r) => {
    const broke = (r.summary?.healed || 0) + (r.summary?.failed || 0);
    return broke ? (r.summary.healed || 0) / broke : null;
  });
  return {
    passRate: { value: poolRate(now), trend: delta(poolRate(now), poolRate(before), { points: true }), series: series(runPassRate) },
    testsExecuted: {
      value: executionTotals?.total ?? (executions || []).length,
      trend: delta(sum(now, 'total'), before.length ? sum(before, 'total') : null),
      series: series((r) => r.summary?.total ?? null),
    },
    issues: {
      value: openFindings + (latest?.summary?.failed || 0),
      trend: delta(sum(now, 'failed'), before.length ? sum(before, 'failed') : null),
      series: series((r) => r.summary?.failed ?? null),
      lowerIsBetter: true,
    },
    healing: { value: heal.rate, trend: null, series: healSeries, attempts: heal.attempts },
  };
}

/** Bars for the last *n* finished runs, oldest first. */
export function runBars(pipelineRuns, n = WINDOW) {
  return finishedRuns(pipelineRuns).slice(0, n).reverse()
    .map((r) => ({ id: r.id, rate: runPassRate(r), label: `#${r.id}`, status: r.status }));
}

const GROUP = {
  smoke: 'Functional', functional: 'Functional', interaction: 'Functional', studio: 'Functional', ai: 'Functional',
  auth: 'Functional', negative: 'Functional', explored: 'Functional', content: 'Content', link: 'Navigation',
  route: 'Navigation', visual: 'Visual', elements: 'Functional', validation: 'Functional', navigation: 'Navigation',
  accessibility: 'Accessibility', responsive: 'Visual',
};

/** Open issues by kind: security findings plus the latest run's failed tests by category. */
export function issueBreakdown({ pipelineRuns, findings: allFindings }) {
  const findings = allFindings || [];
  const counts = new Map();
  const add = (k, n = 1) => counts.set(k, (counts.get(k) || 0) + n);
  const open = findings.filter((f) => (f.status || 'open') === 'open').length;
  if (open) add('Security', open);
  const latest = finishedRuns(pipelineRuns)[0];
  for (const t of latest?.tests || []) {
    if (t.status === 'FAILED') add(GROUP[t.category] || 'Other');
  }
  const total = [...counts.values()].reduce((a, b) => a + b, 0);
  const order = ['Security', 'Functional', 'Content', 'Navigation', 'Accessibility', 'Visual', 'Other'];
  return {
    total,
    parts: order.filter((k) => counts.get(k)).map((k) => ({ label: k, count: counts.get(k), share: counts.get(k) / total })),
  };
}

/** "Good morning" etc. for the local hour. */
export function greeting(hour = new Date().getHours()) {
  if (hour < 5) return 'Good evening';
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}

export const firstName = (name) => (name || '').trim().split(/[\s@]+/)[0] || '';

/**
 * The agents and what each is doing now, from the live run's stages
 * (never "active" unless its stage is running).
 */
export const AGENTS = [
  { id: 'planner', name: 'Test Planner Agent', stage: 'plan', about: 'Plans tests from the page analysis, your goal and the codebase.' },
  { id: 'qa', name: 'QA Execution Agent', stage: 'execute', about: 'Runs the tests in Playwright, in a real browser.' },
  { id: 'healer', name: 'Healing Agent', stage: 'heal', about: 'Repairs broken locators and checks the repair by re-running.' },
  { id: 'security', name: 'Security Agent', stage: 'security', about: 'Passive scan of every page; active probes on verified sites.' },
  { id: 'remediation', name: 'Remediation Agent', stage: null, about: 'Turns findings into fixes and pull requests for you to approve.' },
];

export function agentStates(ws, loop) {
  const run = loop?.run;
  const active = Boolean(loop?.active);
  const stageOf = (key) => run?.stages?.find((s) => s.key === key)?.status;
  return AGENTS.map((a) => {
    let state = 'idle';
    if (a.id === 'security' && ws.scanning) state = 'scanning';
    else if (a.id === 'remediation') {
      const st = loop?.stages?.find((s) => s.id === 'remediate')?.state;
      state = st === 'waiting' ? 'waiting' : 'idle';
    } else if (active) {
      const st = stageOf(a.stage);
      state = st === 'running' ? (a.id === 'security' ? 'scanning' : 'active') : st === 'pending' ? 'queued' : st === 'done' ? 'done' : 'idle';
    }
    return { ...a, state };
  });
}

export const AGENT_STATE = {
  active: ['green', 'Active'], scanning: ['orange', 'Scanning'], queued: ['gray', 'Queued'], done: ['green', 'Done'],
  waiting: ['orange', 'Needs you'], idle: ['gray', 'Idle'],
};

/** Seconds since *iso* (for the live run timer). */
export function elapsed(iso, now = Date.now()) {
  const t = toDate(iso);
  return t ? Math.max(0, Math.floor((now - t.getTime()) / 1000)) : 0;
}

export function clock(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return [h, m, s].map((v) => String(v).padStart(2, '0')).join(':');
}

/** Search the workspace: projects, runs, tests and findings matching *query*. */
export function searchWorkspace(ws, query, limit = 8) {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const hit = (...fields) => fields.some((f) => String(f || '').toLowerCase().includes(q));
  const out = [];
  for (const p of ws.projects || []) {
    if (hit(p.name, p.app_url, p.repo_url)) out.push({ kind: 'Project', label: p.name, detail: p.app_url, page: 'autopilot' });
  }
  for (const r of ws.pipelineRuns || []) {
    if (hit(`#${r.id}`, `run ${r.id}`, r.project_name, r.status)) {
      out.push({ kind: 'Run', label: `Run #${r.id} · ${r.project_name}`, detail: r.status, page: 'runs', tab: String(r.id) });
    }
  }
  for (const t of ws.testCases || []) {
    if (!t.retired && hit(t.name, t.category)) out.push({ kind: 'Test', label: t.name, detail: t.category, page: 'reports' });
  }
  for (const f of ws.findings || []) {
    if (hit(f.title, f.check_id, f.target_url)) out.push({ kind: 'Finding', label: f.title, detail: f.severity, page: 'security' });
  }
  return out.slice(0, limit);
}
