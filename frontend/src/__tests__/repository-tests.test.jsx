import React from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render } from '@testing-library/react';
import RepositoryTests from '../components/RepositoryTests';

afterEach(cleanup);

describe('RepositoryTests', () => {
  it("lists the repository's CI checks with links to their logs", () => {
    const view = render(<RepositoryTests result={{
      source: 'ci', status: 'failed', commit: 'abcdef1234', passed: 1, failed: 1, running: 0,
      detail: 'CI on abcdef1: 1 passed, 1 failed (pytest)',
      checks: [
        { name: 'lint', state: 'passed', conclusion: 'success', url: 'https://ci/lint' },
        { name: 'pytest', state: 'failed', conclusion: 'failure', url: 'https://ci/pytest' },
      ],
    }} />);
    expect(view.getByText('Failed')).toBeTruthy();
    expect(view.container.textContent).toContain('own CI on commit abcdef1: 1 passed, 1 failed (pytest).');
    expect(view.getByRole('link', { name: /pytest/ }).getAttribute('href')).toBe('https://ci/pytest');
    expect(view.getByText('failure')).toBeTruthy();
    expect(view.queryByLabelText('Repository test output')).toBeNull();
  });

  it('shows the sandbox output, open when the tests did not pass', () => {
    const view = render(<RepositoryTests result={{
      source: 'sandbox', framework: 'pytest', status: 'failed', passed: 0, failed: 1,
      detail: 'Sandbox (pytest): 0 passed, 1 failed', output: 'FAILED tests/test_a.py::test_a',
    }} />);
    expect(view.container.textContent).toContain('isolated sandbox (no network while testing, no access to this server): 0 passed, 1 failed.');
    expect(view.getByLabelText('Repository test output').textContent).toContain('FAILED tests/test_a.py::test_a');
    expect(view.container.querySelector('details').open).toBe(true);
  });

  it('renders nothing for a run without repository tests', () => {
    expect(render(<RepositoryTests result={undefined} />).container.innerHTML).toBe('');
  });
});
