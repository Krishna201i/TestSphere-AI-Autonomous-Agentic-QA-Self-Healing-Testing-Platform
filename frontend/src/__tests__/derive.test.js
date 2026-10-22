import { describe, expect, it } from 'vitest';
import { executionStats, pct } from '../lib/derive';

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
