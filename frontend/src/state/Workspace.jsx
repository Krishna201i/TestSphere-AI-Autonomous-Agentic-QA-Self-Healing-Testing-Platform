/**
 * Workspace state shared by every page: backend data, health pulse, the
 * latest security scan, human approvals, retests, pipeline runs and the
 * audit trail.  Scan/approval/audit state is kept in localStorage so a
 * reload does not lose the remediation loop in progress.
 */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import {
  createApplication,
  createProject,
  getApplications,
  getProjects,
  getTestCases,
  getTestExecutions,
  planAndExecute,
  probeHealth,
  securityRetest,
  securityScan,
} from '../services/api';

const STORAGE_KEY = 'testsphere.workspace.v1';
const HEALTH_INTERVAL_MS = 3000;
const HEALTH_SAMPLES = 40;
const DATA_INTERVAL_MS = 15000;
export const OPERATOR = 'dev_active';

const WorkspaceContext = createContext(null);

function loadPersisted() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
  } catch {
    return {};
  }
}

function savePersisted(value) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {
    // storage full or blocked — state still works for this session
  }
}

export function WorkspaceProvider({ children }) {
  const persisted = useRef(loadPersisted()).current;

  const [health, setHealth] = useState([]);
  const [projects, setProjects] = useState([]);
  const [applications, setApplications] = useState([]);
  const [testCases, setTestCases] = useState([]);
  const [executions, setExecutions] = useState([]);

  const [lastScan, setLastScan] = useState(persisted.lastScan || null);
  const [scanHistory, setScanHistory] = useState(persisted.scanHistory || []);
  const [scanning, setScanning] = useState(false);
  const [approvals, setApprovals] = useState(persisted.approvals || {});
  const [retests, setRetests] = useState(persisted.retests || {});
  const [retesting, setRetesting] = useState(null);
  const [selectedKey, setSelectedKey] = useState(persisted.selectedKey || null);

  const [lastRun, setLastRun] = useState(persisted.lastRun || null);
  const [running, setRunning] = useState(null); // label of the run in progress
  const [audit, setAudit] = useState(persisted.audit || []);

  useEffect(() => {
    savePersisted({ lastScan, scanHistory, approvals, retests, selectedKey, lastRun, audit });
  }, [lastScan, scanHistory, approvals, retests, selectedKey, lastRun, audit]);

  const log = useCallback((kind, message, level = 'info') => {
    setAudit((prev) => [{ id: `${Date.now()}-${Math.random()}`, at: new Date().toISOString(), kind, message, level }, ...prev].slice(0, 300));
  }, []);

  // ── Health pulse ────────────────────────────────────────────
  useEffect(() => {
    let alive = true;
    async function tick() {
      const sample = await probeHealth();
      if (alive) setHealth((prev) => [...prev, { ...sample, t: Date.now() }].slice(-HEALTH_SAMPLES));
    }
    tick();
    const id = setInterval(tick, HEALTH_INTERVAL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  // ── Backend records ─────────────────────────────────────────
  const refresh = useCallback(async () => {
    const results = await Promise.allSettled([getProjects(), getApplications(), getTestCases(), getTestExecutions()]);
    const [p, a, t, e] = results.map((r) => (r.status === 'fulfilled' && Array.isArray(r.value) ? r.value : null));
    if (p) setProjects(p);
    if (a) setApplications(a);
    if (t) setTestCases(t);
    if (e) setExecutions(e);
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, DATA_INTERVAL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  // ── Security: scan / approve / retest ───────────────────────
  const runScan = useCallback(async (url) => {
    setScanning(true);
    log('scan', `Passive scan started: ${url}`);
    try {
      const result = await securityScan(url);
      const scan = { ...result, at: new Date().toISOString() };
      setLastScan(scan);
      setScanHistory((prev) => [...prev, { at: scan.at, url, count: result.findings.length }].slice(-12));
      setSelectedKey(result.findings.find((f) => f.remediation?.kind === 'header')?.key || result.findings[0]?.key || null);
      log('scan', `Scan complete: ${result.findings.length} finding(s) on ${url}`, result.findings.length ? 'warn' : 'success');
      return scan;
    } catch (err) {
      log('scan', `Scan refused/failed for ${url}: ${err.message}`, 'error');
      throw err;
    } finally {
      setScanning(false);
    }
  }, [log]);

  const approve = useCallback((finding) => {
    setApprovals((prev) => ({ ...prev, [finding.key]: { at: new Date().toISOString(), by: OPERATOR } }));
    log('approval', `${OPERATOR} approved the fix for ${finding.check_id} (${finding.title})`, 'success');
  }, [log]);

  const retest = useCallback(async (finding) => {
    setRetesting(finding.key);
    log('retest', `Retest started for ${finding.check_id} on ${finding.target_url || finding.component}`);
    try {
      const result = await securityRetest(finding);
      setRetests((prev) => ({ ...prev, [finding.key]: { result: result.retest_result, status: result.status, at: new Date().toISOString() } }));
      log('retest', `${finding.check_id}: retest ${result.retest_result.toUpperCase()} — ${result.status}`, result.retest_result === 'pass' ? 'success' : 'warn');
      return result;
    } catch (err) {
      log('retest', `Retest failed for ${finding.check_id}: ${err.message}`, 'error');
      throw err;
    } finally {
      setRetesting(null);
    }
  }, [log]);

  // ── QA pipeline runs ────────────────────────────────────────
  const runPipeline = useCallback(async (payload, label) => {
    setRunning(label);
    log('qa', `QA pipeline started: ${label}`);
    try {
      const result = await planAndExecute({ headless: true, ...payload });
      setLastRun({ ...result, label, at: new Date().toISOString(), analysis: undefined });
      log('qa', `QA pipeline finished: ${label} → ${result.status}${result.error_message ? ` (${result.error_message})` : ''}`,
        result.status === 'FAILED' ? 'error' : result.status === 'HEALED' ? 'warn' : 'success');
      refresh();
      return result;
    } catch (err) {
      log('qa', `QA pipeline error for ${label}: ${err.message}`, 'error');
      throw err;
    } finally {
      setRunning(null);
    }
  }, [log, refresh]);

  const addTarget = useCallback(async ({ projectName, appName, baseUrl }) => {
    let project = projects.find((p) => p.name === projectName);
    if (!project) project = await createProject({ name: projectName });
    const app = await createApplication({ project_id: project.id, name: appName, base_url: baseUrl });
    log('target', `Target registered: ${appName} (${baseUrl})`, 'success');
    refresh();
    return app;
  }, [projects, log, refresh]);

  const value = useMemo(() => ({
    health, projects, applications, testCases, executions, refresh,
    lastScan, scanHistory, scanning, runScan,
    approvals, approve, retests, retest, retesting, selectedKey, setSelectedKey,
    lastRun, running, runPipeline, addTarget,
    audit, log,
  }), [health, projects, applications, testCases, executions, refresh, lastScan, scanHistory, scanning, runScan,
    approvals, approve, retests, retest, retesting, selectedKey, lastRun, running, runPipeline, addTarget, audit, log]);

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace() {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error('useWorkspace must be used inside <WorkspaceProvider>');
  return ctx;
}
