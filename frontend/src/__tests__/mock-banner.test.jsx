import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';

const ws = vi.hoisted(() => ({ current: {} }));
vi.mock('../state/Workspace', () => ({ useWorkspace: () => ws.current, WorkspaceProvider: ({ children }) => children }));

const { MockModelBanner } = await import('../App');

afterEach(cleanup);

describe('MockModelBanner', () => {
  it('says plainly that the AI is scripted when the server runs the mock model', () => {
    ws.current = { system: { llm: { provider: 'mock', model: 'mock-model' } } };
    render(<MockModelBanner />);
    expect(screen.getByRole('status').textContent).toMatch(/offline demo mode/i);
  });

  it('is not shown with a real model, or before the system info loads', () => {
    ws.current = { system: { llm: { provider: 'chain', model: 'gemini' } } };
    const { container, rerender } = render(<MockModelBanner />);
    expect(container.textContent).toBe('');
    ws.current = { system: null };
    rerender(<MockModelBanner />);
    expect(container.textContent).toBe('');
  });
});
