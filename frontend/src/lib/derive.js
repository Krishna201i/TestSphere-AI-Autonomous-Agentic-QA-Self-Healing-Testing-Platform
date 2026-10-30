/**
 * Pure helpers turning workspace data into what the cards display.
 * Everything here is computed from real records — no placeholder numbers.
 */

export const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low', 'info'];
const SEVERITY_WEIGHT = { critical: 1, high: 0.8, medium: 0.5, low: 0.25, info: 0.1 };

export const RADAR_AXES = [
  { id: 'headers', label: 'Headers', checks: ['SEC-HDR-CSP', 'SEC-HDR-FRAME', 'SEC-HDR-XCTO', 'SEC-HDR-REFERRER'] },
  { id: 'transport', label: 'Transport', checks: ['SEC-HDR-HSTS', 'SEC-TRANSPORT-HTTP'] },
  { id: 'cookies', label: 'Cookies', checks: ['SEC-COOKIE-FLAGS'] },
  { id: 'cors', label: 'CORS', checks: ['SEC-CORS'] },
  { id: 'disclosure', label: 'Disclosure', checks: ['SEC-DISCLOSURE'] },
  { id: 'content', label: 'Content', checks: ['SEC-MIXED-CONTENT', 'SEC-FORM-PASSWORD'] },
];

/** Exposure per radar axis in [0, 1] (severity-weighted, saturating). */
export function radarValues(findings = []) {
  return RADAR_AXES.map((axis) => {
    const sum = findings
      .filter((f) => axis.checks.includes(f.check_id))
      .reduce((acc, f) => acc + (SEVERITY_WEIGHT[f.severity] || 0), 0);
    return Math.min(1, sum / 1.2);
  });
}

export function topFinding(findings = []) {
  return [...findings].sort((a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity))[0] || null;
}

export function pathOf(url) {
  try {
    const u = new URL(url);
    return `${u.host}${u.pathname}`;
  } catch {
    return url;
  }
}

/**
 * Pass rate over executions: PASSED and HEALED count as passing.  `totals`
 * (server counts over all executions, from /api/test-executions/stats) wins
 * over counting the loaded list, which holds only the most recent ones.
 */
export function executionStats(executions = [], totals = null) {
  const done = executions.filter((e) => ['PASSED', 'FAILED', 'HEALED'].includes(e.status));
  const passed = totals ? totals.passed : done.filter((e) => e.status === 'PASSED').length;
  const healed = totals ? totals.healed : done.filter((e) => e.status === 'HEALED').length;
  const failed = totals ? totals.failed : done.filter((e) => e.status === 'FAILED').length;
  const total = passed + healed + failed;
  return {
    total,
    passed,
    healed,
    failed,
    passRate: total ? (passed + healed) / total : null,
    healRate: healed + failed ? healed / (healed + failed) : null,
  };
}

export function retestStats(retests = {}) {
  const all = Object.values(retests);
  const pass = all.filter((r) => r.result === 'pass').length;
  return { total: all.length, pass, rate: all.length ? pass / all.length : null };
}

export function healthStats(samples = []) {
  const ok = samples.filter((s) => s.ok);
  const last = samples[samples.length - 1];
  return {
    online: Boolean(last?.ok),
    dbDown: Boolean(last?.ok && last.db === 'error'),
    dbError: last?.dbError || null,
    successRate: samples.length ? ok.length / samples.length : null,
    latency: last?.ok ? last.ms : null,
  };
}

export const pct = (v, digits = 1) => (v == null ? '—' : `${(v * 100).toFixed(digits)}%`);

/**
 * The testing loop: seven stages that run in a cycle, each with what is built
 * ("built" / "partial" / "planned") and its live state from the newest
 * pipeline run, scans, approvals and retests.
 */
export const LOOP_STAGES = [
  { id: 'ingest', num: '1', title: 'Codebase Ingestion', short: 'Ingest', runKeys: ['codebase'], built: 'built', page: 'visualizer',
    about: 'Reads the repository: languages, frameworks, routes, existing tests and committed secrets. Nothing in it is executed.' },
  { id: 'qa', num: '2A', title: 'AI QA Agent', short: 'Test', runKeys: ['analyze', 'plan', 'execute', 'heal'], built: 'built', page: 'autopilot',
    about: 'Analyzes the live page, plans tests, runs them in Playwright and self-heals broken locators.' },
  { id: 'attack', num: '2B', title: 'AI Attacker Agent', short: 'Attack', runKeys: ['security'], built: 'built', page: 'attacker',
    about: 'Passive, scope-checked security scan: headers, cookies, CORS, TLS and forms. No payloads are sent.' },
  { id: 'report', num: '3', title: 'Unified Reporting', short: 'Report', runKeys: ['report'], built: 'built', page: 'reports',
    about: 'Test results, regressions since the previous run and security findings in one report.' },
  { id: 'remediate', num: '4', title: 'AI Remediation', short: 'Fix', runKeys: [], built: 'partial', page: 'remediation',
    about: 'Proposes fixes for a human to approve, and turns header, CORS and cookie findings into a patch against your repository.' },
  { id: 'validate', num: '5', title: 'Validation Engine', short: 'Verify', runKeys: [], built: 'built', page: 'validation',
    about: 'Re-runs the original check after a fix. A failed retest goes back to remediation.' },
  { id: 'deploy', num: '6', title: 'Verified Deploy', short: 'Deploy', runKeys: [], built: 'built', page: 'validation',
    about: 'Calls your deploy hook, waits until the new version is healthy, runs the smoke tests, and rolls back if either fails.' },
];

const RUN_ACTIVE = ['queued', 'running'];
export const DEPLOY_ACTIVE = ['queued', 'deploying', 'verifying', 'rolling_back'];
export const DEPLOY_LABEL = {
  queued: 'Queued', deploying: 'Deploying', verifying: 'Verifying', rolling_back: 'Rolling back', verified: 'Verified',
  failed: 'Failed', rolled_back: 'Rolled back', rollback_failed: 'Rollback failed', error: 'Error',
};

/** Loop state of stage 6 from the newest deployment. */
export function deployState(deployments = [], projects = []) {
  const d = deployments[0];
  if (!d) {
    const configured = projects.some((p) => p.deploy_hook_url);
    return { state: 'idle', note: configured ? 'Ready to deploy' : 'Add a deploy hook' };
  }
  const short = d.commit ? ` · ${d.commit.slice(0, 7)}` : '';
  if (DEPLOY_ACTIVE.includes(d.status)) return { state: 'running', note: `${DEPLOY_LABEL[d.status]}${short}` };
  if (d.status === 'verified') return { state: 'done', note: `Verified${short}` };
  if (d.status === 'rolled_back') return { state: 'waiting', note: 'Rolled back' };
  return { state: 'failed', note: DEPLOY_LABEL[d.status] || d.status };
}

/** One state for several pipeline-run stages: running beats failed beats done. */
export function mergeStageStatus(statuses) {
  if (!statuses.length) return null;
  if (statuses.includes('running')) return 'running';
  if (statuses.includes('failed')) return 'failed';
  if (statuses.every((s) => s === 'skipped')) return 'skipped';
  if (statuses.every((s) => s === 'done' || s === 'skipped')) return 'done';
  if (statuses.some((s) => s === 'done')) return 'running'; // between two of its steps
  return 'pending';
}

/**
 * Loop model for the diagram: per-stage `state` (running / done / failed /
 * waiting / skipped / pending / idle / planned) with a short `note`, the run
 * it reflects, and how far round the loop that run got.
 */
export function loopModel(ws) {
  const runs = ws.pipelineRuns || [];
  const run = runs.find((r) => RUN_ACTIVE.includes(r.status)) || runs[0] || null;
  const active = Boolean(run && RUN_ACTIVE.includes(run.status));
  const runStage = (key) => run?.stages?.find((s) => s.key === key) || null;

  const findings = ws.lastScan?.findings || [];
  const awaitingApproval = findings.filter((f) => f.remediation?.kind === 'header' && !ws.approvals?.[f.key]).length;
  const approved = findings.filter((f) => ws.approvals?.[f.key]);
  const awaitingRetest = approved.filter((f) => ws.retests?.[f.key]?.result !== 'pass').length;
  const verified = approved.length - awaitingRetest;

  const stages = LOOP_STAGES.map((st) => {
    const parts = st.runKeys.map(runStage).filter(Boolean);
    let state = mergeStageStatus(parts.map((p) => p.status)) || 'idle';
    const current = parts.find((p) => p.status === 'running');
    let note = current?.label || null;

    if (st.id === 'ingest' && ws.ingesting) state = 'running';
    if (st.id === 'qa' && ws.running) { state = 'running'; note = 'Running tests'; }
    if (st.id === 'attack' && ws.scanning) { state = 'running'; note = 'Scanning'; }
    if (st.id === 'remediate') {
      if (awaitingApproval) { state = 'waiting'; note = `${awaitingApproval} fix${awaitingApproval === 1 ? '' : 'es'} to approve`; }
      else if (approved.length) { state = 'done'; note = `${approved.length} approved`; }
    }
    if (st.id === 'validate') {
      if (ws.retesting) { state = 'running'; note = 'Retesting'; }
      else if (awaitingRetest) { state = 'waiting'; note = `${awaitingRetest} to retest`; }
      else if (verified) { state = 'done'; note = `${verified} verified`; }
    }
    if (st.id === 'deploy') ({ state, note } = deployState(ws.deployments, ws.projects));
    if (st.built === 'planned') state = 'planned';
    if (!note && state === 'failed') note = parts.find((p) => p.status === 'failed')?.detail?.split('\n')[0] || null;
    if (!active && state === 'pending') state = 'idle';
    return { ...st, state, note };
  });

  const running = stages.find((s) => s.state === 'running') || null;
  const runKeys = LOOP_STAGES.flatMap((s) => s.runKeys);
  const finishedSteps = run ? (run.stages || []).filter((s) => ['done', 'skipped', 'failed'].includes(s.status)).length : 0;
  // Furthest stage this run reached (index into LOOP_STAGES)
  let reached = -1;
  stages.forEach((s, i) => {
    if (s.runKeys.length && ['done', 'running', 'failed', 'skipped'].includes(s.state)) reached = i;
  });

  return {
    stages,
    run,
    active,
    running,
    reached,
    progress: run ? finishedSteps / runKeys.length : 0,
    attention: stages.filter((s) => s.state === 'waiting'),
    cycles: runs.filter((r) => !RUN_ACTIVE.includes(r.status)).length,
  };
}

/**
 * Parse a backend timestamp.  SQLite-backed endpoints return naive ISO
 * strings that are actually UTC; without a zone, browsers would read them as
 * local time.
 */
export function toDate(iso) {
  if (!iso) return new Date(NaN);
  const hasZone = /([zZ]|[+-]\d\d:?\d\d)$/.test(iso);
  return new Date(hasZone ? iso : `${iso}Z`);
}

export function timeAgo(iso) {
  if (!iso) return '';
  const s = Math.max(0, Math.round((Date.now() - toDate(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

/** "in 5m" for a future time, "due now" once it has passed. */
export function timeUntil(iso) {
  if (!iso) return '';
  const s = Math.round((toDate(iso).getTime() - Date.now()) / 1000);
  if (s <= 0) return 'due now';
  if (s < 3600) return `in ${Math.max(1, Math.round(s / 60))}m`;
  if (s < 86400) return `in ${Math.round(s / 3600)}h`;
  return `in ${Math.round(s / 86400)}d`;
}

/** Returns an error message for anything but a single http(s) URL, else null. */
export function urlError(value) {
  const v = (value || '').trim();
  if (!v) return 'Enter a URL.';
  if ((v.match(/https?:\/\//gi) || []).length > 1) return 'That looks like two URLs joined together — paste just one.';
  try {
    const u = new URL(v);
    if (!['http:', 'https:'].includes(u.protocol)) return 'Use an http:// or https:// URL.';
  } catch {
    return 'Not a valid URL — include http:// or https://.';
  }
  return null;
}

// ── Test results in reports ────────────────────────────────

/** Test types in report order, with what a passing test of that type verified (for runs before checks were recorded). */
export const TEST_GROUPS = [
  { key: 'smoke', label: 'Smoke', about: 'Page loads; title and body render' },
  { key: 'functional', label: 'Goal scenario', about: 'The written goal: form filled and its outcome checked' },
  { key: 'explored', label: 'AI-explored goal', about: 'The goal as the AI explorer reached it, replayed' },
  { key: 'content', label: 'Content', about: 'The main heading is on the page' },
  { key: 'link', label: 'Linked pages', about: 'Linked page loads with its title and heading' },
  { key: 'route', label: 'Code routes', about: 'Route found in the code loads' },
  { key: 'ai', label: 'AI-written tests', about: 'Scenario written by the AI planner' },
  { key: 'saved', label: 'Saved tests', about: 'Saved test' },
];
const GROUP_KEYS = new Set(TEST_GROUPS.map((g) => g.key));

export const groupOf = (t) => (GROUP_KEYS.has(t.category) ? t.category : 'saved');

export function resultLabel(t) {
  return t.healed && t.status === 'PASSED' ? 'HEALED' : t.status;
}

export function formatDuration(ms) {
  if (ms == null) return null;
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`;
}

/** What a result says in its Details cell: the error when it failed, else what it checked. */
export function testDetail(t) {
  const time = formatDuration(t.duration_ms);
  if (t.status === 'FAILED' && t.error) {
    return { kind: 'error', text: t.error.split('\n')[0].replace(/\\n/g, ' '), time };
  }
  const checks = (t.checks || []).filter(Boolean);
  const about = TEST_GROUPS.find((g) => g.key === groupOf(t)).about;
  const parts = [checks.length ? checks.join(' · ') : about];
  if (t.healed) parts.push('a broken locator was healed');
  if (t.status === 'FAILED') parts.push('failed without an error message');
  return { kind: t.status === 'FAILED' ? 'error' : 'ok', text: parts.join(' — '), time };
}

/** A run's results in report order: by test type, failures first within each type. */
export function groupedResults(tests = []) {
  const rank = { FAILED: 0, HEALED: 1, PASSED: 2 };
  return TEST_GROUPS.map((g) => ({
    ...g,
    tests: tests.filter((t) => groupOf(t) === g.key)
      .sort((a, b) => (rank[resultLabel(a)] ?? 1) - (rank[resultLabel(b)] ?? 1) || a.execution_id - b.execution_id),
  })).filter((g) => g.tests.length);
}
