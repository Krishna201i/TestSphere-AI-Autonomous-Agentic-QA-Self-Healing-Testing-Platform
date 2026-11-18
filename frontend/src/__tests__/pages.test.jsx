import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';

const api = vi.hoisted(() => ({
  getPipelineRun: vi.fn(),
  getPipelineRuns: vi.fn(),
  getRunShares: vi.fn(async () => []),
  quickPipeline: vi.fn(),
}));
vi.mock('../services/api', async (importOriginal) => ({ ...(await importOriginal()), ...api }));

const ws = vi.hoisted(() => ({ current: {} }));
vi.mock('../state/Workspace', () => ({ useWorkspace: () => ws.current }));

// jsdom has no ResizeObserver; the charts only need it to exist
globalThis.ResizeObserver ??= class { observe() {} disconnect() {} };

const { default: Autopilot } = await import('../pages/Autopilot');
const { default: Reports } = await import('../pages/Reports');
const { default: RunDetail, aiTokens } = await import('../pages/RunDetail');

const NOW = new Date().toISOString();

function workspace(overrides = {}) {
  return {
    projects: [], findings: [], testCases: [], pipelineRuns: [], system: null,
    refresh: vi.fn(), refreshRuns: vi.fn(), refreshDeployments: vi.fn(), ...overrides,
  };
}

function run(id, overrides = {}) {
  return {
    id, project_id: 1, project_name: 'Shop', status: 'passed', trigger: 'manual', actor: 'ann',
    created_at: NOW, started_at: NOW, finished_at: NOW, regressions: [],
    stages: [{ key: 'execute', label: 'Execute tests', status: 'done', detail: '2 of 2 passed' }],
    summary: { total: 2, passed: 2, failed: 0, healed: 1, narrative: [] },
    tests: [
      { execution_id: 11, test_case_id: 101, name: 'Smoke: Shop', category: 'smoke', status: 'PASSED' },
      { execution_id: 12, test_case_id: 102, name: 'Log in', category: 'functional', status: 'PASSED', healed: true },
    ],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  ws.current = workspace();
  api.getPipelineRun.mockImplementation(async (id) => run(Number(id)));
});
afterEach(cleanup);

describe('Autopilot', () => {
  const urlField = () => screen.getByLabelText('Target URL');
  const submit = () => fireEvent.submit(urlField().closest('form'));

  it('refuses a malformed URL without starting a run', () => {
    render(<Autopilot onNavigate={vi.fn()} />);
    fireEvent.change(urlField(), { target: { value: 'https://a.example/https://b.example' } });
    submit();
    expect(screen.getByText(/two URLs joined together/)).toBeTruthy();
    expect(api.quickPipeline).not.toHaveBeenCalled();
  });

  it('starts the pipeline with the trimmed fields and refreshes the run list', async () => {
    api.quickPipeline.mockResolvedValue(run(7, { status: 'queued' }));
    render(<Autopilot onNavigate={vi.fn()} />);
    fireEvent.change(urlField(), { target: { value: '  https://shop.example/  ' } });
    fireEvent.change(screen.getByLabelText('What to test (optional)'), { target: { value: ' log in ' } });
    submit();
    await waitFor(() => expect(ws.current.refreshRuns).toHaveBeenCalled());
    expect(api.quickPipeline).toHaveBeenCalledWith({ url: 'https://shop.example/', prompt: 'log in', repo_url: null });
    expect(ws.current.refresh).toHaveBeenCalled();
  });

  it('lists the projects, or says how to make one', () => {
    const { unmount } = render(<Autopilot onNavigate={vi.fn()} />);
    expect(screen.getByText(/No projects yet/)).toBeTruthy();
    unmount();
    ws.current = workspace({ projects: [{ id: 1, name: 'Shop', app_url: 'https://shop.example/' }] });
    render(<Autopilot onNavigate={vi.fn()} />);
    const table = screen.getByRole('table');
    expect(within(table).getByText('Shop')).toBeTruthy();
    expect(within(table).getByText('https://shop.example/')).toBeTruthy();
  });
});

describe('Reports', () => {
  const tile = (label) => screen.getByText(label, { selector: '.l' }).previousSibling.textContent;

  it('adds up finished runs only, and narrows to one project', async () => {
    ws.current = workspace({ projects: [{ id: 1, name: 'Shop' }, { id: 2, name: 'Blog' }] });
    api.getPipelineRuns.mockResolvedValue([
      run(1),
      run(2, { project_id: 2, project_name: 'Blog', status: 'failed', summary: { total: 4, passed: 1, failed: 3, healed: 0 } }),
      run(3, { status: 'running', summary: null }),
    ]);
    render(<Reports onNavigate={vi.fn()} />);
    await screen.findByText('Completed runs');
    expect(tile('Completed runs')).toBe('2');
    expect(tile('Tests executed')).toBe('6');
    expect(tile('Self-healed')).toBe('1');

    fireEvent.change(screen.getByLabelText('Project'), { target: { value: '2' } });
    expect(tile('Completed runs')).toBe('1');
    expect(tile('Tests executed')).toBe('4');
    expect(api.getPipelineRuns).toHaveBeenCalledWith(200);
  });

  it('shows why results could not be loaded', async () => {
    api.getPipelineRuns.mockRejectedValue(new Error('Sign in required.'));
    render(<Reports onNavigate={vi.fn()} />);
    expect((await screen.findByRole('alert')).textContent).toContain('Sign in required.');
  });
});

describe('RunDetail', () => {
  it('shows the run: stages, results, tests and what its AI calls used', async () => {
    api.getPipelineRun.mockResolvedValue(run(9, {
      llm_usage: { calls: 3, input_tokens: 9000, output_tokens: 3500, limit: 300000, budget_exhausted: false },
    }));
    render(<RunDetail params={{ tab: '9' }} onNavigate={vi.fn()} />);
    expect(await screen.findByRole('heading', { name: 'Run #9 · Shop' })).toBeTruthy();
    expect(screen.getByText('2 of 2 passed')).toBeTruthy();
    expect(screen.getByText('Log in')).toBeTruthy();
    expect(screen.getByText('HEALED')).toBeTruthy(); // a passing test that healed reads as healed
    expect(screen.getByText('12.5k / 300k')).toBeTruthy();
    expect(screen.getByText('AI tokens · 3 calls')).toBeTruthy();
    expect(api.getPipelineRun).toHaveBeenCalledWith('9');
  });

  it('says when a run cannot be shown', async () => {
    api.getPipelineRun.mockRejectedValue(new Error('Run not found'));
    render(<RunDetail params={{ tab: '404' }} onNavigate={vi.fn()} />);
    expect(await screen.findByText('Run #404 is not available')).toBeTruthy();
    expect(screen.getByText('Run not found')).toBeTruthy();
  });

  it('opens a test at its own address', async () => {
    api.getPipelineRun.mockResolvedValue(run(9));
    const onNavigate = vi.fn();
    render(<RunDetail params={{ tab: '9' }} onNavigate={onNavigate} />);
    fireEvent.click((await screen.findByText('Log in')).closest('tr'));
    expect(onNavigate).toHaveBeenCalledWith('runs', { tab: '9/12' });
  });

  it("shows a test's quarantine as it is now, not as the run saw it", async () => {
    ws.current = workspace({ testCases: [{ id: 101, quarantined: true }, { id: 102, quarantined: false }] });
    api.getPipelineRun.mockResolvedValue(run(9, {
      tests: run(9).tests.map((t) => ({ ...t, quarantined: t.test_case_id === 102 })),
    }));
    render(<RunDetail params={{ tab: '9' }} onNavigate={vi.fn()} />);
    const smoke = (await screen.findByText('Smoke: Shop')).closest('tr');
    expect(within(smoke).queryByText('Quarantined')).toBeTruthy();
    expect(within(screen.getByText('Log in').closest('tr')).queryByText('Quarantined')).toBeNull();
  });
});

describe('aiTokens', () => {
  it('shortens counts and shows the budget when there is one', () => {
    expect(aiTokens({ input_tokens: 400, output_tokens: 100, limit: null })).toBe('500');
    expect(aiTokens({ input_tokens: 1200, output_tokens: 300, limit: 2000 })).toBe('1.5k / 2.0k');
    expect(aiTokens({ input_tokens: 250000, output_tokens: 60000, limit: 300000 })).toBe('310k / 300k');
  });
});
