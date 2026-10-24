import { describe, expect, it } from 'vitest';
import { executionStats, loopModel, mergeStageStatus, pct } from '../lib/derive';

const run = (status) => ({ status });

describe('executionStats', () => {
  it('counts the loaded list when no server totals are available', () => {
    const ex = executionStats([run('PASSED'), run('HEALED'), run('FAILED'), run('RUNNING')]);
    expect(ex).toMatchObject({ total: 3, passed: 1, healed: 1, failed: 1 });
    expect(ex.passRate).toBeCloseTo(2 / 3);
    expect(ex.healRate).toBeCloseTo(1 / 2);
  });

  it('prefers server totals over the (recent-only) list', () => {
    const recent = [run('FAILED'), run('FAILED')];
    const ex = executionStats(recent, { total: 260, passed: 150, healed: 30, failed: 80 });
    expect(ex.total).toBe(260);
    expect(ex.passRate).toBeCloseTo(180 / 260);
  });

  it('has no rates before anything finished', () => {
    const ex = executionStats([], { total: 0, passed: 0, healed: 0, failed: 0 });
    expect(ex.passRate).toBeNull();
    expect(ex.healRate).toBeNull();
    expect(pct(ex.passRate)).toBe('—');
  });
});

describe('mergeStageStatus', () => {
  it('reports running while any step runs, or between two steps', () => {
    expect(mergeStageStatus(['done', 'running', 'pending'])).toBe('running');
    expect(mergeStageStatus(['done', 'pending'])).toBe('running');
  });
  it('fails if any step failed, and is done when all are done or skipped', () => {
    expect(mergeStageStatus(['done', 'failed'])).toBe('failed');
    expect(mergeStageStatus(['done', 'skipped'])).toBe('done');
    expect(mergeStageStatus(['skipped'])).toBe('skipped');
    expect(mergeStageStatus(['pending', 'pending'])).toBe('pending');
    expect(mergeStageStatus([])).toBeNull();
  });
});

describe('loopModel', () => {
  const KEYS = ['codebase', 'analyze', 'plan', 'execute', 'heal', 'security', 'report'];
  const pipelineRun = (id, status, statuses) => ({
    id, status, project_name: 'Shop', stages: KEYS.map((key, i) => ({ key, label: key, status: statuses[i] })),
  });
  const ws = (extra = {}) => ({ pipelineRuns: [], approvals: {}, retests: {}, lastScan: null, ...extra });
  const state = (m, id) => m.stages.find((s) => s.id === id).state;

  it('follows the active run: done, running, then queued stages', () => {
    const run = pipelineRun(2, 'running', ['done', 'done', 'done', 'running', 'pending', 'pending', 'pending']);
    const m = loopModel(ws({ pipelineRuns: [run, pipelineRun(1, 'passed', KEYS.map(() => 'done'))] }));
    expect(m.active).toBe(true);
    expect(m.run.id).toBe(2);
    expect(state(m, 'ingest')).toBe('done');
    expect(state(m, 'qa')).toBe('running');
    expect(m.running.id).toBe('qa');
    expect(state(m, 'attack')).toBe('pending');
    expect(m.progress).toBeCloseTo(3 / 7);
    expect(m.cycles).toBe(1);
  });

  it('shows a finished run as idle-safe: no queued stages, no running token', () => {
    const run = pipelineRun(1, 'failed', ['skipped', 'done', 'done', 'failed', 'pending', 'pending', 'pending']);
    const m = loopModel(ws({ pipelineRuns: [run] }));
    expect(m.active).toBe(false);
    expect(m.running).toBeNull();
    expect(state(m, 'qa')).toBe('failed');
    expect(state(m, 'attack')).toBe('idle');
  });

  it('asks for approval and retests, and keeps deploy planned', () => {
    const findings = [
      { key: 'a', remediation: { kind: 'header' } },
      { key: 'b', remediation: { kind: 'header' } },
    ];
    const m = loopModel(ws({ lastScan: { findings }, approvals: { b: { by: 'me' } }, retests: {} }));
    expect(state(m, 'remediate')).toBe('waiting');
    expect(m.stages.find((s) => s.id === 'remediate').note).toBe('1 fix to approve');
    expect(state(m, 'validate')).toBe('waiting');
    expect(state(m, 'deploy')).toBe('planned');
    expect(m.attention.map((s) => s.id)).toEqual(['remediate', 'validate']);
  });

  it('has no run before the first one', () => {
    const m = loopModel(ws());
    expect(m.run).toBeNull();
    expect(m.reached).toBe(-1);
    expect(state(m, 'ingest')).toBe('idle');
  });
});

describe('usePersistentState', () => {
  it('remembers a value across mounts and survives bad stored data', async () => {
    const { renderHook, act } = await import('@testing-library/react');
    const { default: usePersistentState } = await import('../lib/usePersistentState');
    localStorage.setItem('testsphere.t.bad', '{not json');
    const bad = renderHook(() => usePersistentState('t.bad', 'all'));
    expect(bad.result.current[0]).toBe('all');

    const first = renderHook(() => usePersistentState('t.filter', 'all'));
    act(() => first.result.current[1]('FAILED'));
    first.unmount();
    const second = renderHook(() => usePersistentState('t.filter', 'all'));
    expect(second.result.current[0]).toBe('FAILED');
  });
});
