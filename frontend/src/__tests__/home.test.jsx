import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';

const api = vi.hoisted(() => ({
  quickPipeline: vi.fn(),
  updateProject: vi.fn(async () => ({})),
  runProjectPipeline: vi.fn(async () => ({})),
  cancelPipelineRun: vi.fn(async () => ({})),
  getIntegrations: vi.fn(async () => [{ provider: 'github', connected: false }]),
  getRunReportPdf: vi.fn(),
}));
const ws = vi.hoisted(() => ({ current: null }));
vi.mock('../services/api', () => api);
vi.mock('../state/Workspace', () => ({ useWorkspace: () => ws.current }));
vi.mock('../components/FixPatch', () => ({ RunFixProposal: ({ patchId }) => <div>Fix proposal #{patchId}</div> }));
vi.mock('../components/RepositoryTests', () => ({ default: () => <div>Repository test results</div> }));
vi.mock('../components/charts', () => ({ Skeleton: () => <div>Loading</div> }));

const { default: Home, STEPS } = await import('../pages/Home');

const PROJECT = { id: 4, name: 'shop.example', app_url: 'https://shop.example/', repo_url: 'https://github.com/acme/shop', prompt: 'log in' };
const stages = (status) => STEPS.map((s, i) => ({ key: s.key, label: s.title, status: typeof status === 'function' ? status(i) : status,
  detail: `${s.key} detail` }));

function workspace(extra = {}) {
  ws.current = { projects: [], pipelineRuns: [], system: { active_scan: false }, refresh: vi.fn(async () => {}),
    refreshRuns: vi.fn(async () => {}), ...extra };
  return ws.current;
}

const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); });

beforeEach(() => { try { window.localStorage.clear(); } catch { /* none */ } });
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe('Dashboard: first time', () => {
  it('sets up a project in three steps and starts it', async () => {
    const w = workspace();
    api.quickPipeline.mockResolvedValue({ id: 31, project_id: 9 });
    render(<Home onNavigate={vi.fn()} />);
    expect(screen.getByRole('heading', { name: 'Welcome to TestSphere' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Test your app in three steps' })).toBeTruthy();

    // Step 1: the app's address is checked before going on
    fireEvent.change(screen.getByLabelText(/Your app's address/), { target: { value: 'not a url' } });
    fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
    expect(screen.getByRole('alert')).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/Your app's address/), { target: { value: 'https://shop.example/' } });
    fireEvent.change(screen.getByLabelText(/Git repository/), { target: { value: 'https://github.com/acme/shop' } });
    fireEvent.click(screen.getByRole('button', { name: /Continue/ }));

    // Step 2: a goal from the examples, a schedule
    fireEvent.click(screen.getByRole('button', { name: /log in as demo \/ secret/ }));
    fireEvent.change(screen.getByLabelText(/Run again automatically/), { target: { value: '1440' } });
    fireEvent.click(screen.getByRole('button', { name: /Continue/ }));

    // Step 3: review, then start
    expect(screen.getByText('https://github.com/acme/shop')).toBeTruthy();
    expect(screen.getByText('Daily')).toBeTruthy();
    expect(screen.queryAllByText(/needs a repository/)).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: /Start testing/ }));
    await flush();

    expect(api.quickPipeline).toHaveBeenCalledWith({
      url: 'https://shop.example/', prompt: 'log in as demo / secret and reach the dashboard',
      repo_url: 'https://github.com/acme/shop', sign_in_first: false, active_scan: false,
    });
    expect(api.updateProject).toHaveBeenCalledWith(9, { schedule_minutes: 1440 });
    expect(w.refreshRuns).toHaveBeenCalled();
  });

  it('says which steps a project without a repository skips', () => {
    workspace();
    render(<Home onNavigate={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/Your app's address/), { target: { value: 'https://shop.example/' } });
    fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
    fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
    expect(screen.getAllByText(/needs a repository: skipped/)).toHaveLength(2); // reading the code, its own tests
  });
});

describe('Dashboard: a project and its run', () => {
  it('follows a running run step by step and can stop it', async () => {
    const run = { id: 12, project_id: 4, status: 'running', created_at: new Date().toISOString(),
      stages: stages((i) => (i < 3 ? 'done' : i === 3 ? 'running' : 'pending')) };
    workspace({ projects: [PROJECT], pipelineRuns: [run] });
    render(<Home onNavigate={vi.fn()} />);
    await flush();

    expect(screen.getByRole('heading', { name: 'Dashboard' })).toBeTruthy();
    expect(screen.getByText('Testing… step 4 of 9')).toBeTruthy();
    const steps = screen.getByRole('list', { name: 'Steps of this run' }).querySelectorAll('li');
    expect(steps).toHaveLength(9);
    expect(steps[0].className).toContain('done');
    expect(steps[3].className).toContain('running');
    expect(steps[3].textContent).toContain('Working on it…');
    expect(steps[8].textContent).toContain('Waiting');

    fireEvent.click(screen.getByRole('button', { name: 'Stop' }));
    await flush();
    expect(api.cancelPipelineRun).toHaveBeenCalledWith(12);
  });

  it('opens the proposed fixes for approval when a run finishes', async () => {
    const run = { id: 13, project_id: 4, status: 'failed', created_at: new Date().toISOString(), stages: stages('done'),
      summary: { passed: 4, failed: 1, total: 5 }, fix_patch: { id: 21, fixes: 2, pull_request: null }, ai_fix: { id: 22 } };
    workspace({ projects: [PROJECT], pipelineRuns: [run] });
    const onNavigate = vi.fn();
    render(<Home onNavigate={onNavigate} />);
    await flush();

    expect(screen.getByText('Needs attention · 1 of 5 tests failed')).toBeTruthy();
    expect(screen.getByText('Fix proposal #21')).toBeTruthy();
    expect(screen.getByText('Fix proposal #22')).toBeTruthy();
    // Next steps: the fixes, GitHub (a GitHub repository, not connected), a schedule
    const next = screen.getByRole('heading', { name: 'Next steps' }).closest('section');
    expect(next.textContent).toContain('Review the proposed fixes');
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
    expect(onNavigate).toHaveBeenCalledWith('integrations');

    fireEvent.click(screen.getByRole('button', { name: /Run again/ }));
    await flush();
    expect(api.runProjectPipeline).toHaveBeenCalledWith(4, true);
  });

  it('adds the repository and a schedule right on the dashboard, and hides steps that do not apply', async () => {
    const w = workspace({ projects: [{ ...PROJECT, repo_url: null }], pipelineRuns: [
      { id: 14, project_id: 4, status: 'passed', created_at: new Date().toISOString(), stages: stages('done'), summary: { passed: 3, failed: 0, total: 3 } }] });
    render(<Home onNavigate={vi.fn()} />);
    await flush();
    const next = screen.getByRole('heading', { name: 'Next steps' }).closest('section');
    // No fixes were proposed and there is no GitHub repository: neither step is shown (not shown as done either)
    expect(next.textContent).not.toContain('Review the proposed fixes');
    expect(next.textContent).not.toContain('Connect GitHub');

    fireEvent.click(screen.getByRole('button', { name: 'Add it' }));
    fireEvent.change(screen.getByLabelText('Git repository'), { target: { value: 'github.com/acme/shop' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(screen.getByRole('alert').textContent).toContain('https address');
    fireEvent.change(screen.getByLabelText('Git repository'), { target: { value: 'https://github.com/acme/shop' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await flush();
    expect(api.updateProject).toHaveBeenCalledWith(4, { repo_url: 'https://github.com/acme/shop' });

    fireEvent.change(screen.getByLabelText('Run automatically'), { target: { value: '60' } });
    await flush();
    expect(api.updateProject).toHaveBeenCalledWith(4, { schedule_minutes: 60 });
    expect(w.refresh).toHaveBeenCalledTimes(2);
  });

  it('adds another project from the dashboard', async () => {
    workspace({ projects: [PROJECT], pipelineRuns: [] });
    render(<Home onNavigate={vi.fn()} />);
    await flush();
    fireEvent.click(screen.getByRole('button', { name: /New project/ }));
    expect(screen.getByRole('heading', { name: 'Add a project' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByRole('heading', { name: 'shop.example' })).toBeTruthy();
  });
});
