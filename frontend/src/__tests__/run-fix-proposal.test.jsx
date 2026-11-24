import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render } from '@testing-library/react';

const api = vi.hoisted(() => ({
  getFixPatch: vi.fn(),
  openPullRequest: vi.fn(),
}));
vi.mock('../services/api', () => ({
  ...api,
  createFixPatch: vi.fn(),
  downloadFixPatch: vi.fn(),
  getFixPatches: vi.fn(async () => []),
}));
vi.mock('../state/Workspace', () => ({ useWorkspace: () => ({ projects: [], refresh: () => {} }) }));

const { RunFixProposal } = await import('../components/FixPatch');

const PATCH = {
  id: 9, run_id: 3, repo: 'https://github.com/acme/shop', commit: 'abcdef1234', frameworks: ['fastapi'],
  created_at: new Date().toISOString(), github: true, pull_request: null,
  applied: [{ check_id: 'SEC-HDR-FRAME', how: 'X-Frame-Options header middleware', file: 'main.py' }],
  manual: [{ check_id: 'SEC-TRANSPORT-HTTP', reason: 'Serve the site over HTTPS' }],
  files: [{ path: 'main.py', verified: true, diff: '--- a/main.py\n+++ b/main.py\n@@ -1 +1,2 @@\n app = FastAPI()\n+# fix\n' }],
  patch: 'diff',
};

const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); });

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe('RunFixProposal', () => {
  it('shows the diff for review, and approving opens the pull request', async () => {
    api.getFixPatch.mockResolvedValue(PATCH);
    api.openPullRequest.mockResolvedValue({ number: 12, url: 'https://github.com/acme/shop/pull/12' });
    const view = render(<RunFixProposal patchId={9} />);
    await flush();

    expect(api.getFixPatch).toHaveBeenCalledWith(9);
    expect(view.getByRole('heading', { name: /Fixes ready for review/ })).toBeTruthy();
    expect(view.getByText(/Nothing has been\s+changed yet/)).toBeTruthy();
    expect(view.getByLabelText('Changes to main.py').textContent).toContain('+# fix');
    expect(view.getByText('Serve the site over HTTPS')).toBeTruthy();

    fireEvent.click(view.getByRole('button', { name: /Approve and open pull request/ }));
    await flush();

    expect(api.openPullRequest).toHaveBeenCalledWith(9);
    expect(view.getByRole('link', { name: /Pull request #12/ }).getAttribute('href')).toBe('https://github.com/acme/shop/pull/12');
    expect(view.getByRole('heading', { name: /Fixes proposed/ })).toBeTruthy();
    expect(view.queryByRole('button', { name: /Approve/ })).toBeNull();
  });

  it("shows an AI fix for failing tests with how it was verified", async () => {
    api.getFixPatch.mockResolvedValue({
      ...PATCH, kind: 'tests', manual: [], explanation: 'add() subtracted instead of adding.',
      applied: [{ check_id: 'TESTS', how: 'add() subtracted instead of adding.', file: 'calc.py' }],
      verification: { before: { passed: 3, failed: 1 }, after: { passed: 4, failed: 0 } },
    });
    const view = render(<RunFixProposal patchId={9} />);
    await flush();
    expect(view.getByRole('heading', { name: /AI fix for failing tests: ready for review/ })).toBeTruthy();
    const text = view.container.textContent;
    expect(text).toContain('1 failing before, all 4 passing with this change. Test files were not changed.');
    expect(text).toContain('add() subtracted instead of adding.');
    expect(view.getByRole('button', { name: /Approve and open pull request/ })).toBeTruthy();
  });

  it('explains when a pull request cannot be opened for the repository', async () => {
    api.getFixPatch.mockResolvedValue({ ...PATCH, github: false, repo: '/srv/shop' });
    const view = render(<RunFixProposal patchId={9} />);
    await flush();
    expect(view.getByText(/GitHub, GitLab or Bitbucket repositories only/)).toBeTruthy();
    expect(view.queryByRole('button', { name: /Approve/ })).toBeNull();
  });

  it('says so when the proposal cannot be loaded', async () => {
    api.getFixPatch.mockRejectedValue(new Error('Fix patch not found'));
    const view = render(<RunFixProposal patchId={9} />);
    await flush();
    expect(view.getByRole('alert').textContent).toContain('Fix patch not found');
  });

  it('presents an exported test suite as tests to commit, not as fixes', async () => {
    api.getFixPatch.mockResolvedValue({
      ...PATCH, kind: 'suite', applied: [], manual: [],
      suite: { tests: 6, verified: 4, workflow: true, groups: ['journeys', 'smoke'] },
      files: [{ path: 'testsphere/tests/smoke.spec.ts', verified: null, diff: '+++ b/testsphere/tests/smoke.spec.ts\n' }],
    });
    const view = render(<RunFixProposal patchId={11} />);
    await flush();
    expect(view.getByRole('heading', { name: /Browser tests ready to commit/ })).toBeTruthy();
    expect(view.container.textContent).toMatch(/6 test\(s\) that passed this run/);
    expect(view.container.textContent).toMatch(/4 also shown to fail on a broken copy/);
    expect(view.container.textContent).toMatch(/GitHub Actions workflow/);
  });
});
