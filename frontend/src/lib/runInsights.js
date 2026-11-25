/**
 * What a run's results add up to, for the run page: tallies by kind of test
 * and by page, timing, and what to do next.  Worked out from the run's own
 * record only (the same rules as the PDF report, app/reporting/document.py).
 */

export const KINDS = [
  ['smoke', 'Smoke', 'The page loads; its title and body render'],
  ['functional', 'Goal & forms', "The written goal and the page's forms, with their outcome checked"],
  ['explored', 'AI-explored goal', 'The goal as the AI explorer reached it, replayed'],
  ['content', 'Content', 'Each heading a visitor reads is still on the page'],
  ['elements', 'Page elements', 'Fields take input, buttons show their label, choices can be made'],
  ['validation', 'Field validation', 'Fields stay required, keep their type and their length limit'],
  ['navigation', 'Navigation', 'Links are shown and lead where they say; reload and Back work'],
  ['accessibility', 'Accessibility', 'Language declared, images described, fields named'],
  ['responsive', 'Responsive layout', 'Each page still shows its content at phone and tablet width'],
  ['link', 'Linked pages', 'Linked page loads with its title and heading'],
  ['route', 'Code routes', 'Route found in the code loads'],
  ['ai', 'AI-written', 'Scenario written by the AI planner (quarantined until trusted)'],
  ['repository', 'Repository tests', "The repository's own Playwright tests, replayed"],
  ['saved', 'Saved tests', 'Tests saved in Test Studio or imported'],
];
const KIND_KEYS = new Set(KINDS.map((k) => k[0]));
export const kindOf = (t) => (KIND_KEYS.has(t.category) ? t.category : 'saved');
export const kindLabel = (key) => (KINDS.find((k) => k[0] === key) || KINDS[KINDS.length - 1])[1];

const passed = (t) => t.status === 'PASSED' || t.status === 'HEALED';

/** Counts for a set of tests: passed (healed among them), failed that count, quarantined failures, time. */
export function tally(tests) {
  const list = tests || [];
  const times = list.map((t) => t.duration_ms).filter((ms) => typeof ms === 'number');
  const out = {
    total: list.length,
    passed: list.filter(passed).length,
    healed: list.filter((t) => passed(t) && t.healed).length,
    failed: list.filter((t) => t.status === 'FAILED' && !t.quarantined).length,
    quarantined: list.filter((t) => t.status === 'FAILED' && t.quarantined).length,
    time: times.reduce((a, b) => a + b, 0),
    avg: times.length ? times.reduce((a, b) => a + b, 0) / times.length : null,
  };
  out.rate = out.total ? Math.round((100 * out.passed) / out.total) : 0;
  return out;
}

/** One row per kind of test that ran, in a fixed order. */
export function byKind(tests) {
  const groups = new Map();
  for (const t of tests || []) {
    const k = kindOf(t);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(t);
  }
  return KINDS.filter(([k]) => groups.has(k)).map(([key, label, about]) => ({ key, label, about, ...tally(groups.get(key)) }));
}

/** One row per page the tests start on, most tests first. */
export function byPage(tests) {
  const groups = new Map();
  for (const t of tests || []) {
    const p = t.page || '(other)';
    if (!groups.has(p)) groups.set(p, []);
    groups.get(p).push(t);
  }
  return [...groups.entries()]
    .map(([page, list]) => ({ page, kinds: new Set(list.map(kindOf)).size, ...tally(list) }))
    .sort((a, b) => b.total - a.total || a.page.localeCompare(b.page));
}

/** "850 ms", "4.2 s", "3 min 12 s". */
export function duration(ms) {
  if (ms == null) return '';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 120000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.floor(ms / 60000)} min ${Math.round((ms % 60000) / 1000)} s`;
}

/** Milliseconds between two timestamps, or null. */
export function span(start, end) {
  const a = Date.parse(start);
  const b = Date.parse(end);
  return Number.isFinite(a) && Number.isFinite(b) && b >= a ? b - a : null;
}

/** Median, 90th percentile, slowest and fastest test time, and the slowest tests. */
export function timing(tests, n = 10) {
  const timed = (tests || []).filter((t) => typeof t.duration_ms === 'number');
  if (!timed.length) return null;
  const sorted = timed.map((t) => t.duration_ms).sort((a, b) => a - b);
  return {
    total: sorted.reduce((a, b) => a + b, 0),
    median: sorted[Math.floor(sorted.length / 2)],
    p90: sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.9))],
    slowest: [...timed].sort((a, b) => b.duration_ms - a.duration_ms).slice(0, n),
    max: sorted[sorted.length - 1],
    min: sorted[0],
  };
}

/** Every page the run analyzed: the start page first. */
export function auditedPages(run) {
  const a = run?.analysis || {};
  return [a.start, ...(a.pages || [])].filter(Boolean);
}

/** What to do next, most urgent first: [{ level: 'bad' | 'warn' | 'ok', title, detail }]. */
export function recommendations(run, tests) {
  const list = tests || [];
  const recs = [];
  const add = (level, title, detail) => recs.push({ level, title, detail });
  const failing = list.filter((t) => t.status === 'FAILED' && !t.quarantined);
  if (failing.length) {
    const causes = new Map();
    failing.forEach((t) => t.diagnosis?.label && causes.set(t.diagnosis.label, (causes.get(t.diagnosis.label) || 0) + 1));
    const top = [...causes.entries()].sort((a, b) => b[1] - a[1])[0];
    add('bad', `Fix ${failing.length} failing test${failing.length === 1 ? '' : 's'}`,
      `They fail the run. Open each for its diagnosis, failing step and screenshot.${top ? ` Most common cause: ${top[0]} (${top[1]}).` : ''}`);
  }
  const regressions = run?.regressions || [];
  if (regressions.length) {
    add('bad', `Look at ${regressions.length} regression${regressions.length === 1 ? '' : 's'} first`,
      'These passed in the previous run and fail now: the likeliest sign of a change that broke something.');
  }
  const findings = run?.security_findings || [];
  const proven = findings.filter((f) => f.tier === 'proven');
  if (proven.length) add('bad', `Fix ${proven.length} proven security issue${proven.length === 1 ? '' : 's'}`, 'The scan showed the harm itself. See Security findings for the evidence and the fix.');
  const healed = list.filter((t) => t.healed);
  if (healed.length) {
    add('warn', `Update ${healed.length} self-healed locator${healed.length === 1 ? '' : 's'}`,
      'They passed only because a broken locator was repaired during the run. Open each test to see the old and new locator.');
  }
  const flaky = list.filter((t) => t.flaky);
  if (flaky.length) add('warn', `Stabilise ${flaky.length} flaky test${flaky.length === 1 ? '' : 's'}`, 'Their result keeps changing between runs: usually late-loading content or shared state.');
  const quarantined = list.filter((t) => t.status === 'FAILED' && t.quarantined);
  if (quarantined.length) {
    add('warn', `Review ${quarantined.length} quarantined failure${quarantined.length === 1 ? '' : 's'}`,
      'They do not fail the run. Either the app has a problem the test found, or the test assumes too much: fix one, then release it.');
  }
  const hardening = findings.filter((f) => f.tier === 'hardening');
  if (hardening.length) add('warn', `Add ${hardening.length} missing defence${hardening.length === 1 ? '' : 's'}`, 'Missing security headers or cookie flags: no harm shown, but each is a cheap layer of protection.');
  const pages = auditedPages(run);
  const slow = pages.filter((p) => (p.latency_ms || 0) > 1500);
  if (slow.length) add('warn', `Speed up ${slow.length} slow page${slow.length === 1 ? '' : 's'}`, `First response over 1.5 s: ${slow.slice(0, 3).map((p) => `${p.url} (${p.latency_ms} ms)`).join(', ')}`);
  const noAlt = pages.reduce((n, p) => n + (p.images_without_alt || 0), 0);
  if (noAlt) add('warn', `Describe ${noAlt} image${noAlt === 1 ? '' : 's'} with alt text`, 'Screen-reader users hear nothing, or the file name, for these images.');
  const noLang = pages.filter((p) => !p.lang);
  if (noLang.length) add('warn', `Declare the language of ${noLang.length} page${noLang.length === 1 ? '' : 's'}`, 'Add lang="…" to <html> so screen readers use the right voice.');
  if (!recs.length && list.length) add('ok', 'Nothing to fix', 'Every test that counts passed, nothing regressed and the scan proved no issue.');
  return recs;
}

/** Tests narrowed by kind, result and a search over name, page and checks. */
export function filterTests(tests, { kind = 'all', result = 'all', query = '' } = {}) {
  const q = query.trim().toLowerCase();
  return (tests || []).filter((t) => {
    if (kind !== 'all' && kindOf(t) !== kind) return false;
    if (result === 'failed' && t.status !== 'FAILED') return false;
    if (result === 'passed' && !passed(t)) return false;
    if (result === 'healed' && !t.healed) return false;
    if (result === 'quarantined' && !t.quarantined) return false;
    if (!q) return true;
    return [t.name, t.page, t.about, t.error, ...(t.checks || [])].some((v) => String(v || '').toLowerCase().includes(q));
  });
}
