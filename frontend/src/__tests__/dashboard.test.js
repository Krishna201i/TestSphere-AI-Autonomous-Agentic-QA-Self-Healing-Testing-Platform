import { describe, expect, it } from 'vitest';
import {
  agentStates, clock, delta, elapsed, finishedRuns, firstName, greeting, healStats, issueBreakdown, kpis, runBars,
  runPassRate, searchWorkspace,
} from '../lib/dashboard';

const run = (id, passed, total, extra = {}) => ({
  id, status: 'passed', project_id: 1, project_name: 'Shop', created_at: `2026-11-${String(id).padStart(2, '0')}T10:00:00Z`,
  finished_at: `2026-11-${String(id).padStart(2, '0')}T10:05:00Z`, summary: { total, passed, failed: total - passed, healed: 0 },
  tests: [], ...extra,
});

describe('dashboard numbers', () => {
  it('survives a workspace that is still loading (null everywhere)', () => {
    const ws = { pipelineRuns: null, executions: null, executionTotals: null, findings: null, projects: null };
    const k = kpis(ws);
    expect(k.passRate.value).toBeNull();
    expect(k.testsExecuted.value).toBe(0);
    expect(issueBreakdown(ws)).toEqual({ total: 0, parts: [] });
    expect(runBars(null)).toEqual([]);
    expect(finishedRuns(null)).toEqual([]);
    expect(healStats(null).rate).toBeNull();
  });

  it('finished runs are newest first, without running ones', () => {
    const runs = [run(1, 1, 1), run(3, 1, 1), { ...run(4, 0, 0), status: 'running', summary: null }, run(2, 1, 1)];
    expect(finishedRuns(runs).map((r) => r.id)).toEqual([3, 2, 1]);
  });

  it('pass rate pools tests over the latest 10 runs and compares with the 10 before, in points', () => {
    const older = Array.from({ length: 10 }, (_, i) => run(i + 1, 8, 10));   // 80%
    const newer = Array.from({ length: 10 }, (_, i) => run(i + 11, 9, 10)); // 90%
    const k = kpis({ pipelineRuns: [...older, ...newer], executions: [], findings: [] });
    expect(k.passRate.value).toBeCloseTo(0.9);
    expect(k.passRate.trend).toBeCloseTo(10);
    expect(k.passRate.series).toHaveLength(10);
  });

  it('tests executed is the all-time total; its trend compares tests run per window', () => {
    const runs = [...Array.from({ length: 10 }, (_, i) => run(i + 1, 5, 5)), ...Array.from({ length: 10 }, (_, i) => run(i + 11, 6, 6))];
    const k = kpis({ pipelineRuns: runs, executions: [], executionTotals: { total: 1842 }, findings: [] });
    expect(k.testsExecuted.value).toBe(1842);
    expect(k.testsExecuted.trend).toBeCloseTo(20);
  });

  it('issues are open findings plus the latest run\'s failed tests (fewer is better)', () => {
    const k = kpis({ pipelineRuns: [run(1, 7, 10)], executions: [], findings: [{ status: 'open' }, { status: 'resolved' }] });
    expect(k.issues.value).toBe(4);
    expect(k.issues.lowerIsBetter).toBe(true);
  });

  it('self-healing success counts heals against failures where healing was tried', () => {
    const h = healStats([
      { status: 'HEALED' }, { status: 'HEALED' }, { status: 'HEALED' },
      { status: 'FAILED', error_message: 'Timeout (self-healing tried 2 replacement selector(s); none passed)' },
      { status: 'FAILED', error_message: 'Expected "Products"' }, // an assertion failure: no locator broke
      { status: 'PASSED' },
    ]);
    expect(h).toEqual({ healed: 3, failedHeal: 1, attempts: 4, rate: 0.75 });
  });

  it('delta handles missing and zero baselines', () => {
    expect(delta(5, null)).toBeNull();
    expect(delta(0, 0)).toBe(0);
    expect(delta(3, 0)).toBeNull();
    expect(delta(12, 10)).toBeCloseTo(20);
  });

  it('bars are the last 10 finished runs, oldest first', () => {
    const runs = Array.from({ length: 12 }, (_, i) => run(i + 1, i % 2 ? 1 : 2, 2));
    const bars = runBars(runs);
    expect(bars.map((b) => b.id)).toEqual([3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);
    expect(bars[0]).toMatchObject({ label: '#3', rate: 1 });
    expect(runPassRate(run(1, 0, 0))).toBeNull();
  });

  it('issue breakdown groups findings and the latest run\'s failed tests', () => {
    const latest = run(2, 2, 6, { tests: [
      { status: 'FAILED', category: 'functional' }, { status: 'FAILED', category: 'studio' }, { status: 'FAILED', category: 'content' },
      { status: 'FAILED', category: 'link' }, { status: 'PASSED', category: 'smoke' }, { status: 'FAILED', category: 'whatever' },
    ] });
    const b = issueBreakdown({ pipelineRuns: [run(1, 1, 1), latest], findings: [{ status: 'open' }, { status: 'open' }] });
    expect(b.total).toBe(7);
    expect(b.parts.map((p) => [p.label, p.count])).toEqual([['Security', 2], ['Functional', 2], ['Content', 1], ['Navigation', 1], ['Other', 1]]);
    expect(b.parts.reduce((n, p) => n + p.share, 0)).toBeCloseTo(1);
  });

  it('an agent is active only while its stage runs', () => {
    const live = { id: 9, status: 'running', stages: [{ key: 'plan', status: 'done' }, { key: 'execute', status: 'running' },
      { key: 'heal', status: 'pending' }, { key: 'security', status: 'pending' }] };
    const states = Object.fromEntries(agentStates({ scanning: false }, { run: live, active: true, stages: [] }).map((a) => [a.id, a.state]));
    expect(states).toEqual({ planner: 'done', qa: 'active', healer: 'queued', security: 'queued', remediation: 'idle' });
    const idle = Object.fromEntries(agentStates({ scanning: true }, { run: { ...live, status: 'passed' }, active: false, stages: [] })
      .map((a) => [a.id, a.state]));
    expect(idle).toEqual({ planner: 'idle', qa: 'idle', healer: 'idle', security: 'scanning', remediation: 'idle' });
  });

  it('greets by time of day and first name', () => {
    expect([greeting(8), greeting(14), greeting(20), greeting(2)]).toEqual(['Good morning', 'Good afternoon', 'Good evening', 'Good evening']);
    expect(firstName('Aryan Singh Jadaun')).toBe('Aryan');
    expect(firstName('dev@example.com')).toBe('dev');
    expect(firstName(null)).toBe('');
  });

  it('formats the run timer', () => {
    expect(clock(157)).toBe('00:02:37');
    expect(elapsed('2026-11-23T10:00:00Z', Date.parse('2026-11-23T10:02:37Z'))).toBe(157);
  });

  it('search finds projects, runs, tests and findings', () => {
    const ws = {
      projects: [{ id: 1, name: 'RealWorld FastAPI', app_url: 'https://realworld.example' }],
      pipelineRuns: [{ id: 7842, project_name: 'RealWorld FastAPI', status: 'running' }],
      testCases: [{ name: 'Sign in works', category: 'studio' }, { name: 'Old', retired: true }],
      findings: [{ title: 'Missing CSP header', severity: 'medium' }],
    };
    expect(searchWorkspace(ws, 'realworld').map((h) => h.kind)).toEqual(['Project', 'Run']);
    expect(searchWorkspace(ws, '#7842')[0]).toMatchObject({ page: 'runs', tab: '7842' });
    expect(searchWorkspace(ws, 'sign in')[0].kind).toBe('Test');
    expect(searchWorkspace(ws, 'csp')[0].kind).toBe('Finding');
    expect(searchWorkspace(ws, 'old')).toEqual([]);
    expect(searchWorkspace(ws, '  ')).toEqual([]);
  });
});
