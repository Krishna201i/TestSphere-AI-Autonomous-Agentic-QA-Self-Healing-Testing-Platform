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
 * Pipeline stages with what is actually built ("live" / "partial" / "planned")
 * and which stage needs attention right now.
 */
export function pipelineStages(ws) {
  const findings = ws.lastScan?.findings || [];
  const awaitingApproval = findings.filter((f) => f.remediation?.kind === 'header' && !ws.approvals[f.key]);
  const awaitingRetest = findings.filter((f) => ws.approvals[f.key] && ws.retests[f.key]?.result !== 'pass');

  const stages = [
    { id: 'ingest', num: '1.', title: 'Codebase Ingestion', badge: ws.blueprints.length ? 'Blueprint Ready' : 'Awaiting Codebase', tone: 'gray', status: 'live',
      detail: ws.blueprints.length
        ? `${ws.blueprints.length} codebase(s) analyzed; latest: ${ws.blueprints[0].name} (${ws.blueprints[0].files_total} files, ${ws.blueprints[0].routes} routes, ${ws.blueprints[0].risks} risks).`
        : 'Ingest a Git repository or local folder to build its blueprint.', page: 'pipeline' },
    { id: 'qa', num: '2A.', title: 'AI QA Agent', badge: 'Functional Tests', tone: 'blue', status: 'live',
      detail: 'Plans tests from the live page, runs them in Playwright and self-heals broken locators.', page: 'pipeline' },
    { id: 'attack', num: '2B.', title: 'AI Attacker Agent', badge: 'Authorized Pen-Test', tone: 'orange', status: 'live',
      detail: 'Passive, scope-checked scan (headers, cookies, CORS, TLS). Active payload testing is not built yet.', page: 'attacker' },
    { id: 'report', num: '3.', title: 'Unified Reporting', badge: 'Evidence & Priority', tone: 'gray', status: 'partial',
      detail: 'Security findings share one Finding schema, deduplicated and severity-sorted. QA failures are not merged in yet.', page: 'audit' },
    { id: 'remediate', num: '4.', title: 'AI Remediation', badge: 'Human Approval', tone: 'violet', status: 'partial',
      detail: `${awaitingApproval.length} fix proposal(s) awaiting approval. Proposals cover header/cookie config; source-code patches need 5.1.`, page: 'remediation' },
    { id: 'validate', num: '5.', title: 'Validation Engine', badge: 'Sandbox Retest', tone: 'blue', status: 'live',
      detail: `${awaitingRetest.length} approved fix(es) awaiting a passing retest. Retests re-run the original check.`, page: 'validation' },
    { id: 'deploy', num: '6.', title: 'Verified Deploy', badge: 'Health Check & Rollback', tone: 'green', status: 'planned',
      detail: 'Deployment, health checks and rollback for target apps are not built yet (module 5.7).', page: 'validation' },
  ];

  let active = 'ingest';
  if (ws.ingesting) active = 'ingest';
  else if (ws.running) active = 'qa';
  else if (ws.scanning) active = 'attack';
  else if (awaitingApproval.length) active = 'remediate';
  else if (awaitingRetest.length) active = 'validate';
  else if (ws.blueprints.length && !ws.lastScan) active = 'attack';
  else if (ws.lastScan) active = 'report';

  return { stages, active };
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
