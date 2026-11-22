import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';

const api = vi.hoisted(() => ({
  draftStudioTest: vi.fn(),
  verifyStudioSteps: vi.fn(),
  getStudioTests: vi.fn(async () => []),
  saveStudioTest: vi.fn(async () => ({ id: 9 })),
  updateStudioTest: vi.fn(async () => ({ id: 9 })),
  planAndExecute: vi.fn(),
  exportPlaywright: vi.fn(),
}));
vi.mock('../services/api', async (importOriginal) => ({ ...(await importOriginal()), ...api }));

const ws = vi.hoisted(() => ({ current: {} }));
vi.mock('../state/Workspace', () => ({ useWorkspace: () => ws.current }));

const { default: TestStudio } = await import('../pages/TestStudio');

const SHOP = { id: 1, name: 'Shop', app_url: 'https://shop.example/login' };
const step = (action, target, value, status) => ({ action, target, value, description: `${action} ${target || ''}`, status, note: null });
const DRAFT = {
  name: 'Sign in', instruction: 'log in as demo', start_url: SHOP.app_url, source: 'ai', note: null,
  not_covered: ['see the invoices'], problems: [], quarantine: false,
  steps: [
    step('FILL', '#user', 'demo', 'found'),
    step('CLICK', '#login', null, 'found'),
    step('ASSERT_CONTAINS_TEXT', 'body', 'Products', 'found'),
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  window.scrollTo = vi.fn(); // jsdom has no scrolling
  ws.current = { projects: [SHOP, { id: 2, name: 'No site' }], refresh: vi.fn() };
  api.draftStudioTest.mockResolvedValue(DRAFT);
});
afterEach(cleanup);

async function draftIt() {
  render(<TestStudio onNavigate={vi.fn()} />);
  fireEvent.change(screen.getByLabelText('What should the test do?'), { target: { value: 'log in as demo' } });
  fireEvent.click(screen.getByRole('button', { name: /write the steps/i }));
  await screen.findByText('Review the steps');
}

describe('Test Studio', () => {
  it('asks for a project with a site first', () => {
    const onNavigate = vi.fn();
    ws.current = { projects: [{ id: 2, name: 'No site' }], refresh: vi.fn() };
    render(<TestStudio onNavigate={onNavigate} />);
    expect(screen.getByText('No project with a site yet')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Open Autopilot' }));
    expect(onNavigate).toHaveBeenCalledWith('autopilot');
  });

  it('writes steps from the description and shows how each finds its element', async () => {
    await draftIt();
    expect(api.draftStudioTest).toHaveBeenCalledWith(1, { instruction: 'log in as demo', start_path: null });
    expect(screen.getByText('Written by AI')).toBeTruthy();
    expect(screen.getAllByText('On the page')).toHaveLength(3);
    expect(screen.getByText('see the invoices')).toBeTruthy();
    expect(screen.getByLabelText('Step 1 element').value).toBe('#user');
  });

  it('saves the reviewed steps without the check results', async () => {
    await draftIt();
    fireEvent.click(screen.getByRole('button', { name: 'Save test' }));
    await waitFor(() => expect(api.saveStudioTest).toHaveBeenCalled());
    const [projectId, body] = api.saveStudioTest.mock.calls[0];
    expect(projectId).toBe(1);
    expect(body.name).toBe('Sign in');
    expect(body.steps[0]).toEqual({ action: 'FILL', target: '#user', value: 'demo', description: 'FILL #user' });
    expect(body.steps[1].value).toBeNull();
    expect(Object.keys(body.steps[2])).not.toContain('status');
    await waitFor(() => expect(api.getStudioTests).toHaveBeenCalledTimes(2)); // the list reloads
  });

  it('an edited step must be checked against the page again before saving', async () => {
    api.verifyStudioSteps.mockResolvedValue({ ...DRAFT, steps: [...DRAFT.steps.slice(0, 2), step('ASSERT_CONTAINS_TEXT', 'body', 'Cart', 'found')] });
    await draftIt();
    fireEvent.change(screen.getByLabelText('Step 3 value'), { target: { value: 'Cart' } });
    expect(screen.getByText('Edited: check again')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Save test' }).disabled).toBe(true);

    fireEvent.click(screen.getByRole('button', { name: 'Check against the page' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save test' }).disabled).toBe(false));
    expect(api.verifyStudioSteps.mock.calls[0][1].steps[2].value).toBe('Cart');
  });

  it('a test without a check cannot be saved', async () => {
    api.draftStudioTest.mockResolvedValue({ ...DRAFT, steps: DRAFT.steps.slice(0, 2) });
    await draftIt();
    expect(screen.getByText('Add at least one check, or the test cannot fail.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Save test' }).disabled).toBe(true);
  });

  it('runs a saved test and shows its result', async () => {
    api.getStudioTests.mockResolvedValue([{ id: 7, name: 'Sign in', version: 2, quarantined: true, instruction: 'log in',
      steps: [step('NAVIGATE', null, SHOP.app_url, 'page'), ...DRAFT.steps], last_result: null }]);
    api.planAndExecute.mockResolvedValue({ status: 'HEALED', error_message: 'Self-healed #login -> #sign-in' });
    render(<TestStudio onNavigate={vi.fn()} />);
    const row = (await screen.findByText('Sign in')).closest('tr');
    expect(within(row).getByText('Quarantined')).toBeTruthy();
    expect(within(row).getByText('Not run')).toBeTruthy();

    fireEvent.click(within(row).getByRole('button', { name: /run/i }));
    expect(await within(row).findByText('HEALED')).toBeTruthy();
    expect(api.planAndExecute).toHaveBeenCalledWith({ test_case_id: 7 });
    expect(within(row).getByText('Self-healed #login -> #sign-in')).toBeTruthy();
  });

  it('opens a saved test for editing without its first "open the page" step', async () => {
    api.getStudioTests.mockResolvedValue([{ id: 7, name: 'Sign in', version: 1, quarantined: false, instruction: 'log in',
      steps: [step('NAVIGATE', null, SHOP.app_url, 'page'), ...DRAFT.steps], last_result: null }]);
    render(<TestStudio onNavigate={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    expect(screen.getByText('Edit test')).toBeTruthy();
    expect(screen.getByLabelText('Step 1 element').value).toBe('#user');
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeTruthy();
  });

  it('shows why a draft failed', async () => {
    api.draftStudioTest.mockRejectedValue(new Error('Could not load https://shop.example/login (HTTP 503)'));
    render(<TestStudio onNavigate={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('What should the test do?'), { target: { value: 'log in' } });
    fireEvent.click(screen.getByRole('button', { name: /write the steps/i }));
    expect((await screen.findByRole('alert')).textContent).toContain('HTTP 503');
  });
});
