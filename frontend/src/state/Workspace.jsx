/**
 * Workspace state shared by every page: backend records, health pulse,
 * tracked security findings (with approvals and retests), pipeline runs and
 * the audit trail.
 *
 * Findings, approvals, retests and audit events live on the server, so every
 * viewer sees the same trail.  Only view conveniences (which scan is shown,
 * the selected finding, the last run's details) are kept in localStorage.
 */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import {
  approveFinding,
  createApplication,
  createProject,
  getApplications,
  getAudit,
  getFindings,
  getProjects,
  getTestCases,
  getTestExecutions,
  planAndExecute,
  probeHealth,
  retestFinding,
  securityScan,
} from '../services/api';
import { toDate } from '../lib/derive';

const STORAGE_KEY = 'testsphere.workspace.v2';
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
    // storage full or blocked — the view just won't be restored on reload
  }
}

export function WorkspaceProvider({ children }) {
  const persisted = useRef(loadPersisted()).current;

  const [health, setHealth] = useState([]);
  const [projects, setProjects] = useState([]);
  const [applications, setApplications] = useState([]);
  const [testCases, setTestCases] = useState([]);
  const [executions, setExecutions] = useState([]);
  const [findings, setFindings] = useState([]); // every tracked finding (server)
  const [serverAudit, setServerAudit] = useState([]);
  const [clientErrors, setClientErrors] = useState([]); // failures that never reached the server

  // Scan metadata only; the findings themselves come from `findings`
  const [scanMeta, setScanMeta] = useState(persisted.scanMeta || null);
  const [scanHistory, setScanHistory] = useState(persisted.scanHistory || []);
  const [scanning, setScanning] = useState(false);
  const [retesting, setRetesting] = useState(null);
  const [selectedKey, setSelectedKey] = useState(persisted.selectedKey || null);
  const [lastRun, setLastRun] = useState(persisted.lastRun || null);
  const [running, setRunning] = useState(null);

  useEffect(() => {
    savePersisted({ scanMeta, scanHistory, selectedKey, lastRun });
  }, [scanMeta, scanHistory, selectedKey, lastRun]);

  const noteError = useCallback((kind, message) => {
    setClientErrors((prev) => [{ id: `c-${Date.now()}`, at: new Date().toISOString(), actor: OPERATOR, kind, level: 'error', message }, ...prev].slice(0, 50));
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
    const results = await Promise.allSettled([
      getProjects(), getApplications(), getTestCases(), getTestExecutions(), getFindings(), getAudit(),
    ]);
    const [p, a, t, e, f, au] = results.map((r) => (r.status === 'fulfilled' && Array.isArray(r.value) ? r.value : null));
    if (p) setProjects(p);
    if (a) setApplications(a);
    if (t) setTestCases(t);
    if (e) setExecutions(e);
    if (f) setFindings(f);
    if (au) setServerAudit(au);
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, DATA_INTERVAL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  const upsertFinding = useCallback((updated) => {
    setFindings((prev) => {
      const rest = prev.filter((f) => f.key !== updated.key);
      return [updated, ...rest];
    });
  }, []);

  // ── Security: scan / approve / retest ───────────────────────
  const runScan = useCallback(async (url) => {
    setScanning(true);
    try {
      const result = await securityScan(url, OPERATOR);
      const at = new Date().toISOString();
      setScanMeta({
        url: result.url, final_url: result.final_url, status_code: result.status_code, at,
        summary: result.summary, response_headers: result.response_headers,
        keys: result.findings.map((f) => f.key), resolvedCount: result.resolved.length,
      });
      setScanHistory((prev) => [...prev, { at, url, count: result.findings.length }].slice(-12));
      setFindings((prev) => {
        const fresh = new Map([...result.findings, ...result.resolved].map((f) => [f.key, f]));
        return [...fresh.values(), ...prev.filter((f) => !fresh.has(f.key))];
      });
      setSelectedKey(result.findings.find((f) => f.remediation?.kind === 'header')?.key || result.findings[0]?.key || null);
      return result;
    } catch (err) {
      if (!err.status) noteError('scan', `Scan of ${url} failed: ${err.message}`);
      throw err;
    } finally {
      setScanning(false);
      getAudit().then(setServerAudit).catch(() => {});
    }
  }, [noteError]);

  const approve = useCallback(async (finding) => {
    try {
      upsertFinding(await approveFinding(finding.key, OPERATOR));
    } catch (err) {
      noteError('approval', `Approval of ${finding.check_id} failed: ${err.message}`);
      throw err;
    } finally {
      getAudit().then(setServerAudit).catch(() => {});
    }
  }, [upsertFinding, noteError]);

  const retest = useCallback(async (finding) => {
    setRetesting(finding.key);
    try {
      const updated = await retestFinding(finding.key, OPERATOR);
      upsertFinding(updated);
      return updated;
    } catch (err) {
      if (!err.status) noteError('retest', `Retest of ${finding.check_id} failed: ${err.message}`);
      throw err;
    } finally {
      setRetesting(null);
      getAudit().then(setServerAudit).catch(() => {});
    }
  }, [upsertFinding, noteError]);

  // ── QA pipeline runs ────────────────────────────────────────
  const runPipeline = useCallback(async (payload, label) => {
    setRunning(label);
    try {
      const result = await planAndExecute({ headless: true, ...payload });
      setLastRun({ ...result, label, at: new Date().toISOString(), analysis: undefined });
      return result;
    } catch (err) {
      noteError('qa', `QA run for ${label} failed: ${err.message}`);
      throw err;
    } finally {
      setRunning(null);
      refresh();
    }
  }, [refresh, noteError]);

  const addTarget = useCallback(async ({ projectName, appName, baseUrl }) => {
    let project = projects.find((p) => p.name === projectName);
    if (!project) project = await createProject({ name: projectName });
    const app = await createApplication({ project_id: project.id, name: appName, base_url: baseUrl });
    refresh();
    return app;
  }, [projects, refresh]);

  // ── Derived views (what the cards consume) ──────────────────
  // Findings of the scan on screen: the last scan's keys, or else the most
  // recently scanned target's open findings (e.g. on a fresh browser).
  const lastScan = useMemo(() => {
    if (scanMeta) {
      const byKey = new Map(findings.map((f) => [f.key, f]));
      return { ...scanMeta, findings: scanMeta.keys.map((k) => byKey.get(k)).filter(Boolean) };
    }
    const open = findings.filter((f) => f.status === 'open');
    if (!open.length) return null;
    const target = open[0].target_url;
    const list = open.filter((f) => f.target_url === target);
    return { url: target, final_url: target, at: list[0].last_seen, findings: list, response_headers: [], summary: null };
  }, [scanMeta, findings]);

  const approvals = useMemo(() => Object.fromEntries(
    findings.filter((f) => f.approved_by).map((f) => [f.key, { by: f.approved_by, at: f.approved_at }]),
  ), [findings]);

  const retests = useMemo(() => Object.fromEntries(
    findings.filter((f) => f.retest_result).map((f) => [f.key, { result: f.retest_result, status: f.status, at: f.retested_at }]),
  ), [findings]);

  const audit = useMemo(
    () => [...serverAudit, ...clientErrors].sort((a, b) => toDate(b.at) - toDate(a.at)),
    [serverAudit, clientErrors],
  );

  const value = useMemo(() => ({
    health, projects, applications, testCases, executions, findings, refresh,
    lastScan, scanHistory, scanning, runScan,
    approvals, approve, retests, retest, retesting, selectedKey, setSelectedKey,
    lastRun, running, runPipeline, addTarget, audit,
  }), [health, projects, applications, testCases, executions, findings, refresh, lastScan, scanHistory, scanning, runScan,
    approvals, approve, retests, retest, retesting, selectedKey, lastRun, running, runPipeline, addTarget, audit]);

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace() {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error('useWorkspace must be used inside <WorkspaceProvider>');
  return ctx;
}
