import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { byKind, byPage, filterTests, recommendations, tally, timing } from '../lib/runInsights';

const api = vi.hoisted(() => ({ getPipelineRun: vi.fn(), getRunShares: vi.fn(async () => []) }));
vi.mock('../services/api', async (importOriginal) => ({ ...(await importOriginal()), ...api }));
const ws = vi.hoisted(() => ({ current: {} }));
vi.mock('../state/Workspace', () => ({ useWorkspace: () => ws.current }));

const { default: RunDetail } = await import('../pages/RunDetail');

const TESTS = [
  { execution_id: 1, test_case_id: 1, name: 'Smoke: Shop', category: 'smoke', status: 'PASSED', page: '/', duration_ms: 1200 },
  { execution_id: 2, test_case_id: 2, name: "Heading 'Deals' is shown · /", category: 'content', status: 'PASSED', page: '/',
    checks: ["Page shows 'Deals'"], about: 'A heading a visitor reads is still on the page', duration_ms: 900 },
  { execution_id: 3, test_case_id: 3, name: "Field 'Email' is still required · /signup", category: 'validation', status: 'FAILED',
    page: '/signup', error: "assert_hidden failed: '#email:not([required])' is still visible", diagnosis: { label: 'Check did not hold' },
    duration_ms: 3100 },
  { execution_id: 4, test_case_id: 4, name: "Clicking 'About' opens /about · /", category: 'navigation', status: 'PASSED', healed: true,
    page: '/', duration_ms: 2500 },
  { execution_id: 5, test_case_id: 5, name: 'Page shows its content on a phone (390 px wide) · /', category: 'responsive',
    status: 'FAILED', quarantined: true, page: '/', duration_ms: 1500 },
];
const PAGE = {
  url: 'https://shop.example/', title: 'Shop', status_code: 200, latency_ms: 2100, lang: null, html_kb: 40,
  rendered_in_browser: true, visibility_checked: true, counts: { inputs: 3, buttons: 2, links: 12 }, headings: ['Deals'],
  images_without_alt: 2, headers: { server: 'nginx' },
  health: { overall_score: 71, security: { score: 60, is_https: true, hsts: false, csp: false, x_frame_options: true, x_content_type_options: true },
    accessibility: { score: 80, missing_image_alts: 2 }, performance: { score: 70, rating: 'Moderate' } },
};

describe('run insights', () => {
  it('tallies passes, heals, counting and quarantined failures', () => {
    expect(tally(TESTS)).toMatchObject({ total: 5, passed: 3, healed: 1, failed: 1, quarantined: 1, rate: 60, time: 9200 });
  });

  it('groups by kind in a fixed order and by page with the busiest first', () => {
    expect(byKind(TESTS).map((r) => r.key)).toEqual(['smoke', 'content', 'validation', 'navigation', 'responsive']);
    expect(byPage(TESTS).map((r) => [r.page, r.total])).toEqual([['/', 4], ['/signup', 1]]);
  });

  it('filters by kind, result and a search over names, pages and checks', () => {
    expect(filterTests(TESTS, { result: 'failed' }).map((t) => t.execution_id)).toEqual([3, 5]);
    expect(filterTests(TESTS, { kind: 'validation' })).toHaveLength(1);
    expect(filterTests(TESTS, { query: 'deals' }).map((t) => t.execution_id)).toEqual([2]);
    expect(filterTests(TESTS, { query: '/signup' }).map((t) => t.execution_id)).toEqual([3]);
    expect(filterTests(TESTS, { result: 'healed' }).map((t) => t.execution_id)).toEqual([4]);
  });

  it('works out what to do next from the run itself', () => {
    const recs = recommendations({ regressions: [{}], security_findings: [{ tier: 'hardening' }], analysis: { start: PAGE } }, TESTS);
    expect(recs.map((r) => r.title)).toEqual([
      'Fix 1 failing test', 'Look at 1 regression first', 'Update 1 self-healed locator', 'Review 1 quarantined failure',
      'Add 1 missing defence', 'Speed up 1 slow page', 'Describe 2 images with alt text', 'Declare the language of 1 page',
    ]);
    expect(recs[0].detail).toContain('Most common cause: Check did not hold (1)');
    expect(recommendations({}, TESTS.filter((t) => t.status === 'PASSED' && !t.healed))[0].title).toBe('Nothing to fix');
  });

  it('times the run', () => {
    const t = timing(TESTS, 2);
    expect(t.slowest.map((x) => x.execution_id)).toEqual([3, 4]);
    expect(t.max).toBe(3100);
    expect(t.min).toBe(900);
  });
});

describe('RunDetail in depth', () => {
  beforeEach(() => {
    ws.current = { testCases: [], refresh: vi.fn() };
    api.getPipelineRun.mockResolvedValue({
      id: 7, project_name: 'Shop', status: 'failed', trigger: 'manual', created_at: '2026-11-01T10:00:00Z',
      started_at: '2026-11-01T10:00:00Z', finished_at: '2026-11-01T10:04:00Z', regressions: [],
      stages: [{ key: 'execute', label: 'Execute tests', status: 'failed', detail: '3 of 5 passed', started_at: '2026-11-01T10:01:00Z', finished_at: '2026-11-01T10:03:30Z' }],
      summary: { total: 5, passed: 3, failed: 1, quarantined_failed: 1, healed: 1, narrative: [] },
      tests: TESTS,
      analysis: { start: PAGE, pages: [] },
      security_findings: [{ check_id: 'SEC-HDR-CSP', title: 'No Content-Security-Policy', severity: 'low', tier: 'hardening',
        component: 'https://shop.example/', evidence: ['No CSP header'], recommendation: 'Send a CSP header' }],
    });
  });
  afterEach(cleanup);

  it('shows results by kind and page, what to do next, the page audit, findings and timing', async () => {
    render(<RunDetail params={{ tab: '7' }} onNavigate={vi.fn()} />);
    await screen.findByRole('heading', { name: 'Run #7 · Shop' });
    expect(screen.getByRole('heading', { name: /Results by kind of test/ })).toBeTruthy();
    expect(screen.getByRole('heading', { name: /Coverage by page/ })).toBeTruthy();
    expect(screen.getByText('Fix 1 failing test')).toBeTruthy();
    expect(screen.getByText(/· 2 min 30 s/)).toBeTruthy(); // how long the stage took
    const audit = screen.getByRole('heading', { name: /Pages analyzed/ }).closest('section');
    expect(within(audit).getByText('Content-Security-Policy')).toBeTruthy();
    expect(within(audit).getByText('not declared')).toBeTruthy();
    expect(screen.getByText('No Content-Security-Policy')).toBeTruthy();
    expect(screen.getByText('Send a CSP header', { exact: false })).toBeTruthy();
    expect(screen.getByRole('heading', { name: /Timing/ })).toBeTruthy();
    // What a passed test checked is on the list, without opening it
    expect(screen.getByText("Page shows 'Deals'")).toBeTruthy();
  });

  it('narrows the test list by result, search and kind', async () => {
    render(<RunDetail params={{ tab: '7' }} onNavigate={vi.fn()} />);
    await screen.findByRole('heading', { name: 'Run #7 · Shop' });
    const list = () => screen.getByRole('heading', { name: 'Tests' }).closest('section');
    fireEvent.click(within(list()).getByRole('button', { name: 'Failed' }));
    expect(within(list()).getAllByRole('row')).toHaveLength(3); // header + 2 failures
    fireEvent.change(within(list()).getByLabelText('Search tests'), { target: { value: 'signup' } });
    expect(within(list()).getAllByRole('row')).toHaveLength(2);
    fireEvent.change(within(list()).getByLabelText('Search tests'), { target: { value: 'nothing like this' } });
    expect(within(list()).getByText('No test matches these filters.')).toBeTruthy();
    fireEvent.click(within(list()).getByRole('button', { name: 'Show all tests' }));
    // Picking a kind in the results table narrows the list to it
    const kinds = screen.getByRole('heading', { name: /Results by kind of test/ }).closest('section');
    fireEvent.click(within(kinds).getByText('Field validation').closest('tr'));
    expect(within(list()).getAllByRole('row')).toHaveLength(2);
  });
});
