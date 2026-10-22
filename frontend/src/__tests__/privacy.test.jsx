import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('../services/api', () => ({
  deleteMe: vi.fn(),
  getSystem: vi.fn(),
  getMe: vi.fn(),
  updateMe: vi.fn(),
}));
vi.mock('../state/Auth', () => ({ useAuth: () => ({}) }));
vi.mock('../state/Workspace', () => ({ useWorkspace: () => ({}) }));

const api = await import('../services/api');
const { DeleteAccount } = await import('../pages/Profile');
const { PrivacyNotice } = await import('../pages/Privacy');

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('DeleteAccount', () => {
  it('stays disabled until the exact phrase is typed, then erases and reports back', async () => {
    api.deleteMe.mockResolvedValue({ deleted: { projects: 2 }, sign_in_account_deleted: true });
    const onDeleted = vi.fn();
    render(<DeleteAccount onDeleted={onDeleted} />);

    fireEvent.click(screen.getByRole('button', { name: /delete account/i }));
    const confirm = screen.getByRole('button', { name: /delete everything/i });
    const input = screen.getByLabelText(/to confirm/i);
    expect(confirm.disabled).toBe(true);

    fireEvent.change(input, { target: { value: 'delete my account' } });  // wrong case
    expect(confirm.disabled).toBe(true);
    fireEvent.change(input, { target: { value: 'DELETE MY ACCOUNT' } });
    expect(confirm.disabled).toBe(false);

    fireEvent.click(confirm);
    await waitFor(() => expect(onDeleted).toHaveBeenCalled());
    expect(api.deleteMe).toHaveBeenCalledWith('DELETE MY ACCOUNT');
  });

  it('shows the server error and keeps the account when deletion fails', async () => {
    api.deleteMe.mockRejectedValue(new Error('Database unavailable'));
    const onDeleted = vi.fn();
    render(<DeleteAccount onDeleted={onDeleted} />);
    fireEvent.click(screen.getByRole('button', { name: /delete account/i }));
    fireEvent.change(screen.getByLabelText(/to confirm/i), { target: { value: 'DELETE MY ACCOUNT' } });
    fireEvent.click(screen.getByRole('button', { name: /delete everything/i }));
    expect((await screen.findByRole('alert')).textContent).toMatch(/Database unavailable/);
    expect(onDeleted).not.toHaveBeenCalled();
  });
});

describe('PrivacyNotice', () => {
  it.each([
    ['cloud', /sent to that provider/],
    ['local', /own machine/],
    ['none', /nothing is sent to an AI provider/],
  ])('describes AI processing for %s', async (kind, text) => {
    api.getSystem.mockResolvedValue({ privacy: { ai_processing: kind, contact: null, error_reporting: false } });
    render(<PrivacyNotice />);
    expect(await screen.findByText(text)).toBeTruthy();
    expect(screen.getByText(/operator of this TestSphere server/)).toBeTruthy();
  });

  it('links the configured contact', async () => {
    api.getSystem.mockResolvedValue({ privacy: { ai_processing: 'none', contact: 'dpo@example.org', error_reporting: true } });
    render(<PrivacyNotice />);
    const link = await screen.findByRole('link', { name: 'dpo@example.org' });
    expect(link.getAttribute('href')).toBe('mailto:dpo@example.org');
    expect(screen.getByText(/Sentry/)).toBeTruthy();
  });
});
