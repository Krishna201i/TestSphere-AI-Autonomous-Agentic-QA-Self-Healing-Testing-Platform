import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render } from '@testing-library/react';
import { WorkspaceProvider, clearSavedWorkspaces, useWorkspace } from '../state/Workspace';

// Every backend call answers an empty list: only what the browser stores matters here
vi.mock('../services/api', () => {
  const empty = async () => [];
  return {
    approveFinding: empty, createApplication: empty, createProject: empty, getApplications: empty, getAudit: empty,
    getBlueprint: empty, getDeployments: empty, getExecutionStats: async () => null, getFindings: empty,
    getPipelineRuns: empty, getSystem: async () => ({}), ingestCodebase: empty, listBlueprints: empty,
    getProjects: empty, getTestCases: empty, getTestExecutions: empty, planAndExecute: empty,
    probeHealth: async () => ({ ok: true, db: 'ok', ms: 1 }), retestFinding: empty, securityScan: empty,
  };
});

function Probe({ onReady }) {
  onReady(useWorkspace());
  return null;
}

afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe('Saved workspace views', () => {
  it('belong to one account and are removed on sign-out', async () => {
    localStorage.setItem('testsphere.workspace.v2.alice', JSON.stringify({ lastRun: { label: 'https://alice.private/' } }));
    let ws;
    await act(async () => {
      render(<WorkspaceProvider uid="bob"><Probe onReady={(w) => { ws = w; }} /></WorkspaceProvider>);
    });
    expect(ws.lastRun).toBeNull(); // Bob never sees Alice's last run
    expect(localStorage.getItem('testsphere.workspace.v2.bob')).not.toBeNull();

    clearSavedWorkspaces();
    expect(Object.keys(localStorage).filter((k) => k.startsWith('testsphere.workspace'))).toEqual([]);
  });
});
