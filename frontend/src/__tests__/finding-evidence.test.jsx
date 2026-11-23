import React from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import FindingEvidence, { TierPill } from '../components/FindingEvidence';
import { byTier, findingTier, tierCounts } from '../lib/derive';

afterEach(cleanup);

const sqli = {
  key: 'a', check_id: 'SEC-SQLI-ERROR', severity: 'critical', tier: 'proven', confidence: 0.9,
  location: { method: 'GET', url: 'https://shop.test/item', parameter: 'id' },
  prerequisites: 'None: the request needs no account.',
  steps: ['Send it with a quote', 'The response contains a MySQL error.'],
  request: "curl -s 'https://shop.test/item?id=ts1%27'",
  response_excerpt: 'You have an error in your SQL syntax',
  severity_rationale: 'The input reaches a SQL query unescaped.',
  code_location: 'app/views.py:41',
};

describe('finding tiers', () => {
  it('works out the tier of findings stored before tiers existed', () => {
    expect(findingTier({ check_id: 'SEC-HDR-CSP' })).toBe('hardening');
    expect(findingTier({ check_id: 'SEC-XSS-REFLECTED', confidence: 1 })).toBe('proven');
    expect(findingTier({ check_id: 'SEC-XSS-REFLECTED', confidence: 0.9 })).toBe('unconfirmed');
    expect(findingTier({ check_id: 'SEC-EXPOSED-ENV' })).toBe('proven');
    expect(findingTier({ check_id: 'SEC-HDR-CSP', tier: 'proven' })).toBe('proven'); // the server's word wins
  });

  it('puts proven findings first, then by severity, and counts each tier', () => {
    const list = [
      { key: 'h', check_id: 'SEC-HDR-CSP', severity: 'high' },
      { key: 'p', check_id: 'SEC-OPEN-REDIRECT', severity: 'medium' },
      { key: 'u', check_id: 'SEC-CSRF', severity: 'medium' },
      { key: 'c', check_id: 'SEC-SQLI-ERROR', severity: 'critical' },
    ];
    expect(byTier(list).map((f) => f.key)).toEqual(['c', 'p', 'u', 'h']);
    expect(tierCounts(list)).toEqual({ proven: 2, unconfirmed: 1, hardening: 1 });
  });
});

describe('FindingEvidence', () => {
  it('shows where, what it takes, the steps, a copyable command, what came back and why', () => {
    render(<FindingEvidence finding={sqli} />);
    expect(screen.getByText('GET https://shop.test/item · parameter id')).toBeTruthy();
    expect(screen.getByText('app/views.py:41')).toBeTruthy();
    expect(screen.getAllByRole('listitem').map((li) => li.textContent)).toEqual(sqli.steps);
    expect(screen.getByText(sqli.request)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Copy the command' })).toBeTruthy();
    expect(screen.getByText('You have an error in your SQL syntax')).toBeTruthy();
    expect(screen.getByText(/Why critical:/)).toBeTruthy();
  });

  it('shows nothing for an old finding without reproduction details', () => {
    const { container } = render(<FindingEvidence finding={{ check_id: 'SEC-HDR-CSP', severity: 'medium' }} />);
    expect(container.textContent).toBe('');
  });

  it('labels a tier in words', () => {
    render(<TierPill finding={{ check_id: 'SEC-HDR-CSP' }} />);
    expect(screen.getByText('Hardening').getAttribute('title')).toMatch(/nothing was shown/);
  });
});

describe('ActiveTargets', () => {
  it('lists sites with what to publish, and says why active scans are blocked', async () => {
    const { vi } = await import('vitest');
    const api = await import('../services/api');
    vi.spyOn(api, 'getScanTargets').mockResolvedValue({
      targets: [{ id: 1, url: 'https://shop.example', host: 'shop.example', token: 'testsphere-verify=abc',
        file_url: 'https://shop.example/.well-known/testsphere-verify.txt', state: 'pending', needs_proof: true }],
      active_scan: { server: true, allowed: false, reason: 'Active scanning is not enabled for this account', uid: 'u-123', proof_required: true },
    });
    const { default: ActiveTargets } = await import('../components/ActiveTargets');
    render(<ActiveTargets onPick={() => {}} />);
    expect(await screen.findByText('shop.example')).toBeTruthy();
    expect(screen.getByText('Waiting for proof')).toBeTruthy();
    expect(screen.getByText('https://shop.example/.well-known/testsphere-verify.txt')).toBeTruthy();
    expect(screen.getByText('testsphere-verify=abc')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Verify' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Scan it' })).toBeNull(); // not until verified
    expect(screen.getByText(/not enabled for this account/)).toBeTruthy();
    expect(screen.getByText('u-123')).toBeTruthy();
  });
});
