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
  getBlueprint,
  getDeployments,
  getExecutionStats,
  getFindings,
  getPipelineRuns,
  getSystem,
  ingestCodebase,
  listBlueprints,
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
const RUNS_ACTIVE_MS = 2000;
const RUNS_LIMIT = 40;
const ACTIVE_RUN = ['queued', 'running'];
const ACTIVE_DEPLOY = ['queued', 'deploying', 'verifying', 'rolling_back'];
const OPERATOR_KEY = 'testsphere.operator';
export const DEFAULT_OPERATOR = 'dev_active';

function loadOperator() {
  try {
    return localStorage.getItem(OPERATOR_KEY) || DEFAULT_OPERATOR;
  } catch {
    return DEFAULT_OPERATOR;
  }
}

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

  const [operator, setOperatorState] = useState(loadOperator);
  const [system, setSystem] = useState(null);
  const [blueprints, setBlueprints] = useState([]); // summaries
  const [blueprint, setBlueprint] = useState(null); // latest full blueprint
  const [ingesting, setIngesting] = useState(false);
  const [health, setHealth] = useState([]);
  const [projects, setProjects] = useState([]);
  const [applications, setApplications] = useState([]);
  const [testCases, setTestCases] = useState([]);
  const [executions, setExecutions] = useState([]);
  const [executionTotals, setExecutionTotals] = useState(null); // over all executions; `executions` is the recent ones
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
  const [pipelineRuns, setPipelineRuns] = useState(null); // null until the first load
  const [deployments, setDeployments] = useState([]);

  useEffect(() => {
    savePersisted({ scanMeta, scanHistory, selectedKey, lastRun });
  }, [scanMeta, scanHistory, selectedKey, lastRun]);

  const setOperator = useCallback((name) => {
    const clean = (name || '').trim().slice(0, 64) || DEFAULT_OPERATOR;
    setOperatorState(clean);
    try {
      localStorage.setItem(OPERATOR_KEY, clean);
    } catch {
      // not persisted; still used for this session
    }
  }, []);

  const noteError = useCallback((kind, message) => {
    setClientErrors((prev) => [{ id: `c-${Date.now()}`, at: new Date().toISOString(), actor: 'dashboard', kind, level: 'error', message }, ...prev].slice(0, 50));
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
      getProjects(), getApplications(), getTestCases(), getTestExecutions(), getFindings(), getAudit(), listBlueprints(),
    ]);
    const [p, a, t, e, f, au, bps] = results.map((r) => (r.status === 'fulfilled' && Array.isArray(r.value) ? r.value : null));
    if (bps) setBlueprints(bps);
    getSystem().then(setSystem).catch(() => setSystem(null));
    getExecutionStats().then(setExecutionTotals).catch(() => setExecutionTotals(null)); // older backend: count the list
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

  // ── Pipeline runs (Autopilot, the loop) ─────────────────────
  // Followed closely while one is queued or running, otherwise at the data pace
  const refreshRuns = useCallback(async () => {
    try {
      const runs = await getPipelineRuns(RUNS_LIMIT);
      if (Array.isArray(runs)) setPipelineRuns(runs);
    } catch {
      setPipelineRuns((prev) => prev || []);
    }
  }, []);
  const runActive = Boolean(pipelineRuns?.some((r) => ACTIVE_RUN.includes(r.status)));
  useEffect(() => {
    refreshRuns();
    const id = setInterval(refreshRuns, runActive ? RUNS_ACTIVE_MS : DATA_INTERVAL_MS);
    return () => clearInterval(id);
  }, [refreshRuns, runActive]);
  // Deployments: followed every 2 seconds while one is in progress
  const refreshDeployments = useCallback(async () => {
    try {
      const rows = await getDeployments(10);
      if (Array.isArray(rows)) setDeployments(rows);
    } catch {
      // older backend or outage: the loop shows deploy as not configured
    }
  }, []);
  const deployActive = deployments.some((d) => ACTIVE_DEPLOY.includes(d.status));
  useEffect(() => {
    refreshDeployments();
    const id = setInterval(refreshDeployments, deployActive ? RUNS_ACTIVE_MS : DATA_INTERVAL_MS);
    return () => clearInterval(id);
  }, [refreshDeployments, deployActive]);

  // A run finishing changes executions, findings and projects too
  const wasActive = useRef(runActive);
  useEffect(() => {
    if (wasActive.current && !runActive) refresh();
    wasActive.current = runActive;
  }, [runActive, refresh]);

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
      const result = await securityScan(url, operator);
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
  }, [noteError, operator]);

  const approve = useCallback(async (finding) => {
    try {
      upsertFinding(await approveFinding(finding.key, operator));
    } catch (err) {
      noteError('approval', `Approval of ${finding.check_id} failed: ${err.message}`);
      throw err;
    } finally {
      getAudit().then(setServerAudit).catch(() => {});
    }
  }, [upsertFinding, noteError, operator]);

  const retest = useCallback(async (finding) => {
    setRetesting(finding.key);
    try {
      const updated = await retestFinding(finding.key, operator);
      upsertFinding(updated);
      return updated;
    } catch (err) {
      if (!err.status) noteError('retest', `Retest of ${finding.check_id} failed: ${err.message}`);
      throw err;
    } finally {
      setRetesting(null);
      getAudit().then(setServerAudit).catch(() => {});
    }
  }, [upsertFinding, noteError, operator]);

  // ── Codebase ingestion ──────────────────────────────────────
  const ingest = useCallback(async (source) => {
    setIngesting(true);
    try {
      const bp = await ingestCodebase(source, operator);
      setBlueprint(bp);
      return bp;
    } catch (err) {
      if (!err.status) noteError('ingest', `Ingestion of ${source} failed: ${err.message}`);
      throw err;
    } finally {
      setIngesting(false);
      refresh();
    }
  }, [operator, noteError, refresh]);

  const openBlueprint = useCallback(async (id) => {
    setBlueprint(await getBlueprint(id));
  }, []);

  // Show the newest blueprint by default once the list arrives
  useEffect(() => {
    if (!blueprint && blueprints.length) getBlueprint(blueprints[0].id).then(setBlueprint).catch(() => {});
  }, [blueprints, blueprint]);

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
    operator, setOperator, system, blueprints, blueprint, ingest, ingesting, openBlueprint,
    health, projects, applications, testCases, executions, executionTotals, findings, refresh,
    lastScan, scanHistory, scanning, runScan,
    approvals, approve, retests, retest, retesting, selectedKey, setSelectedKey,
    lastRun, running, runPipeline, addTarget, audit, pipelineRuns, refreshRuns, deployments, refreshDeployments,
  }), [pipelineRuns, refreshRuns, deployments, refreshDeployments, health, projects, applications, testCases, executions, executionTotals, findings, refresh, lastScan, scanHistory, scanning, runScan,
    approvals, approve, retests, retest, retesting, selectedKey, lastRun, running, runPipeline, addTarget, audit, operator, setOperator, system, blueprints, blueprint, ingest, ingesting, openBlueprint]);

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace() {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error('useWorkspace must be used inside <WorkspaceProvider>');
  return ctx;
}
