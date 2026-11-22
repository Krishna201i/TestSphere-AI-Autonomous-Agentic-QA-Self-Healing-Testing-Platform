import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';

const api = vi.hoisted(() => ({
  getHeals: vi.fn(),
  reviewHeal: vi.fn(async () => ({})),
  getIntegrations: vi.fn(async () => [{ provider: 'github', connected: false }]),
  getArtifact: vi.fn(async () => new Blob(['png'])),
}));
vi.mock('../services/api', async (importOriginal) => ({ ...(await importOriginal()), ...api }));
const ws = vi.hoisted(() => ({ current: {} }));
vi.mock('../state/Workspace', () => ({ useWorkspace: () => ws.current }));

const { default: SelfHealing } = await import('../pages/SelfHealing');
const { default: TestRuns } = await import('../pages/TestRuns');
const { default: Sidebar } = await import('../components/Sidebar');

const HEAL = { key: '11:#login', execution_id: 11, test_case_id: 3, test_name: 'Sign in', step: 'click Log in', original: '#login',
  selected: '#sign-in', strategy: 'fingerprint', confidence: 0.95, screenshot: null, written_back: true, review: null, at: new Date().toISOString() };

beforeEach(() => {
  vi.clearAllMocks();
  globalThis.URL.createObjectURL ??= () => 'blob:x';
  globalThis.URL.revokeObjectURL ??= () => {};
  ws.current = { pipelineRuns: null, projects: null };
});
afterEach(cleanup);

describe('Self-Healing page', () => {
  it('lists heals to review with their evidence and approves one', async () => {
    api.getHeals.mockResolvedValue({ heals: [HEAL], total: 1, pending: 1, approved: 0, rejected: 0 });
    render(<SelfHealing />);
    const row = (await screen.findByText('Sign in')).closest('tr');
    expect(within(row).getByText('#login')).toBeTruthy();
    expect(within(row).getByText('#sign-in')).toBeTruthy();
    expect(within(row).getByText('Written into the test')).toBeTruthy();
    expect(within(row).getByText('confidence 95%')).toBeTruthy();
    fireEvent.click(within(row).getByRole('button', { name: 'Approve heal of #login' }));
    await waitFor(() => expect(api.reviewHeal).toHaveBeenCalledWith(11, '#login', 'approve'));
    expect(api.getHeals).toHaveBeenCalledTimes(2); // reloaded after the decision
  });

  it('a rejected heal shows who rejected it and can still be approved', async () => {
    api.getHeals.mockResolvedValue({ heals: [{ ...HEAL, review: { decision: 'rejected', by: 'ann', at: HEAL.at } }],
      total: 1, pending: 0, approved: 0, rejected: 1 });
    render(<SelfHealing />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Rejected' }));
    const row = (await screen.findByText('Sign in')).closest('tr');
    expect(within(row).getByText('rejected')).toBeTruthy();
    expect(within(row).queryByRole('button', { name: /Reject heal/ })).toBeNull();
    expect(within(row).getByRole('button', { name: 'Approve heal of #login' })).toBeTruthy();
  });

  it('explains an empty history', async () => {
    api.getHeals.mockResolvedValue({ heals: [], total: 0, pending: 0, approved: 0, rejected: 0 });
    render(<SelfHealing />);
    expect(await screen.findByText('No heals yet')).toBeTruthy();
  });
});

describe('Test Runs page', () => {
  const runs = [
    { id: 8, project_id: 1, project_name: 'Shop', status: 'failed', trigger: 'webhook', created_at: HEAL.at, started_at: HEAL.at,
      finished_at: HEAL.at, summary: { total: 10, passed: 7, failed: 3, healed: 1 } },
    { id: 7, project_id: 2, project_name: 'Blog', status: 'passed', trigger: 'manual', created_at: HEAL.at, started_at: HEAL.at,
      finished_at: HEAL.at, summary: { total: 4, passed: 4, failed: 0, healed: 0 } },
  ];

  it('renders while the workspace is still loading', () => {
    render(<TestRuns onNavigate={vi.fn()} />);
    expect(screen.getByText('No runs yet')).toBeTruthy();
  });

  it('lists runs, filters them and opens one', () => {
    const onNavigate = vi.fn();
    ws.current = { pipelineRuns: runs, projects: [{ id: 1, name: 'Shop' }, { id: 2, name: 'Blog' }] };
    render(<TestRuns onNavigate={onNavigate} />);
    expect(screen.getByText('#8')).toBeTruthy();
    expect(screen.getByText('3 failed')).toBeTruthy();
    expect(screen.getByText('GitHub push')).toBeTruthy();
    fireEvent.click(screen.getByRole('tab', { name: 'Passed' }));
    expect(screen.queryByText('#8')).toBeNull();
    fireEvent.click(screen.getByRole('row', { name: 'Open run 7' }));
    expect(onNavigate).toHaveBeenCalledWith('runs', { tab: '7' });
  });
});

describe('Sidebar', () => {
  it('navigates, opens the AI Agents group and shows the real GitHub state', async () => {
    const onNavigate = vi.fn();
    render(<Sidebar page="studio" onNavigate={onNavigate} open={false} onClose={vi.fn()} />);
    // The group of the current page is open, and its page is marked current
    expect(screen.getByRole('button', { name: 'Test Studio' }).getAttribute('aria-current')).toBe('page');
    fireEvent.click(screen.getByRole('button', { name: 'Self-Healing' }));
    expect(onNavigate).toHaveBeenCalledWith('healing');
    expect(await screen.findByRole('button', { name: 'Connect GitHub' })).toBeTruthy();
    expect(screen.queryByText(/upgrade|pro plan/i)).toBeNull(); // no plan that does not exist
  });
});
