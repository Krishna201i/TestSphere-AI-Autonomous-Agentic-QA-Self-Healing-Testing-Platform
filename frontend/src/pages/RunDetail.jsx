/**
 * One pipeline run, at its own shareable address (#/runs/<id>, or
 * #/runs/<id>/<execution> with a test open): stages, results, and for each
 * test its steps with screenshots, healing evidence and the Playwright trace.
 */
import React, { useEffect, useRef, useState } from 'react';
import {
  ArrowLeft, ArrowRight, Download, ExternalLink, FileCode2, Link2, ShieldOff, Shield, Wand2, X,
} from 'lucide-react';
import { useWorkspace } from '../state/Workspace';
import { getArtifact, getPipelineRun, getTestExecution, updateTestCase } from '../services/api';
import { timeAgo, toDate } from '../lib/derive';
import { selectableRow } from '../lib/a11y';
import { Skeleton } from '../components/charts';
import { RunStatus, StageIcon } from './Autopilot';

const ACTIVE = ['queued', 'running'];
const TRIGGER_LABEL = { manual: 'Manual', schedule: 'Scheduled', webhook: 'GitHub push' };
const STEP_STATUS = { passed: 'PASSED', failed: 'FAILED', healed: 'HEALED', skipped: 'PENDING' };

export const testLabel = (t) => (t.healed && t.status === 'PASSED' ? 'HEALED' : t.status);

function saveBlob(blob, name) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

/** An artifact image fetched with the sign-in token; click to enlarge. */
function Screenshot({ executionId, artifactKey, alt }) {
  const [url, setUrl] = useState(null);
  const [error, setError] = useState(null);
  const dialog = useRef(null);
  useEffect(() => {
    let alive = true;
    let objectUrl = null;
    getArtifact(executionId, artifactKey)
      .then((blob) => { objectUrl = URL.createObjectURL(blob); if (alive) setUrl(objectUrl); })
      .catch((err) => alive && setError(err.message));
    return () => { alive = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [executionId, artifactKey]);

  if (error) return <div className="shot-missing small muted">{error}</div>;
  if (!url) return <span className="skeleton shot-placeholder" aria-hidden="true" />;
  return (
    <>
      <button type="button" className="shot" onClick={() => dialog.current?.showModal()} aria-label={`Enlarge: ${alt}`}>
        <img src={url} alt={alt} />
      </button>
      <dialog ref={dialog} className="lightbox" aria-label={alt} onClick={(e) => { if (e.target === dialog.current) dialog.current.close(); }}>
        <div className="lightbox-head">
          <span className="small">{alt}</span>
          <button type="button" className="icon-btn" onClick={() => dialog.current.close()} aria-label="Close"><X size={18} /></button>
        </div>
        <img src={url} alt={alt} />
      </dialog>
    </>
  );
}

/** What self-healing changed on a step: old and new locator, confidence, alternatives. */
export function HealingEvidence({ healing }) {
  const healed = Boolean(healing.selected_locator);
  return (
    <div className={`heal-box ${healed ? '' : 'refused'}`}>
      <div className="heal-head"><Wand2 size={14} aria-hidden="true" /> {healed ? 'Locator healed' : 'Healing found no safe replacement'}</div>
      <div className="heal-diff">
        <code className="heal-old" title="The locator that broke">{healing.original_locator}</code>
        {healed && <><ArrowRight size={14} aria-hidden="true" className="muted" /><code className="heal-new" title="The locator used instead">{healing.selected_locator}</code></>}
      </div>
      <div className="heal-meta">
        {healing.strategy && <span>Strategy: <b>{healing.strategy}</b></span>}
        <span className="heal-conf">
          Confidence <b>{Math.round(healing.confidence * 100)}%</b>
          <span className="meter" aria-hidden="true"><span style={{ width: `${Math.round(healing.confidence * 100)}%` }} /></span>
        </span>
      </div>
      {healing.candidates?.length > 1 && (
        <details className="heal-cands">
          <summary className="small">Other candidates considered ({healing.candidates.length})</summary>
          <ul className="plain-list small">
            {healing.candidates.map((c) => <li key={c.locator}><code>{c.locator}</code> <span className="muted">{Math.round(c.score * 100)}%</span></li>)}
          </ul>
        </details>
      )}
    </div>
  );
}

function ExecutionDetail({ test, onQuarantine }) {
  const [ex, setEx] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setEx(null);
    setError(null);
    getTestExecution(test.execution_id).then(setEx).catch((err) => setError(err.message));
  }, [test.execution_id]);

  async function download(key, name) {
    try {
      saveBlob(await getArtifact(test.execution_id, key), name);
    } catch (err) {
      setError(err.message);
    }
  }

  async function toggleQuarantine() {
    setBusy(true);
    try {
      await onQuarantine(test, !test.quarantined);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" aria-labelledby="exec-title">
      <div className="card-head">
        <h3 id="exec-title">{test.name}</h3>
        <span className={`status ${testLabel(test)}`}>{testLabel(test)}</span>
      </div>
      <div className="row small">
        <span className="muted">Execution #{test.execution_id}{ex?.duration_ms != null ? ` · ${(ex.duration_ms / 1000).toFixed(1)} s` : ''}</span>
        {test.flaky && <span className="status FLAKY" title="Its result flipped between pass and fail at least twice in recent runs">Flaky</span>}
        {test.quarantined && <span className="pill gray">Quarantined</span>}
      </div>
      <div className="row">
        {ex?.trace && (
          <>
            <button type="button" className="btn btn-sm" onClick={() => download(ex.trace, `trace-${test.execution_id}.zip`)}><Download size={14} /> Trace</button>
            <a className="btn btn-sm btn-ghost" href="https://trace.playwright.dev/" target="_blank" rel="noreferrer">
              <ExternalLink size={14} /> Open trace viewer
            </a>
          </>
        )}
        <button type="button" className="btn btn-sm btn-ghost" onClick={toggleQuarantine} disabled={busy}
          title={test.quarantined ? 'Failures of this test will fail runs again' : 'Keep running it, but stop its failures from failing runs'}>
          {test.quarantined ? <><Shield size={14} /> Release from quarantine</> : <><ShieldOff size={14} /> Quarantine</>}
        </button>
      </div>
      {ex?.trace && <p className="hint m-0">Download the trace, then drop it on the trace viewer to replay every action with the DOM, network and console.</p>}
      {error && <div className="error-text" role="alert">{error}</div>}
      {!ex && !error && <Skeleton lines={4} block />}

      {ex && (ex.steps?.length ? (
        <ol className="step-list">
          {ex.steps.map((st, i) => (
            <li key={st.step_id} className={`step ${st.status}`}>
              <div className="step-head">
                <span className="step-num">{i + 1}</span>
                <span className="step-title cell-wrap">{st.description || st.step_id}</span>
                <span className={`status ${STEP_STATUS[st.status] || ''}`}>{st.status}</span>
                <span className="xsmall muted nowrap">{st.duration_ms} ms</span>
              </div>
              {st.locator && <div className="step-loc small"><code>{st.locator}</code></div>}
              {st.error && st.status === 'failed' && <pre className="step-error">{st.error}</pre>}
              {st.healing && <HealingEvidence healing={st.healing} />}
              {(st.screenshot || st.dom) && (
                <div className="step-artifacts">
                  {st.screenshot && <Screenshot executionId={test.execution_id} artifactKey={st.screenshot} alt={`Step ${i + 1}: ${st.description || st.step_id}`} />}
                  {st.dom && (
                    <button type="button" className="link-btn small" onClick={() => download(st.dom, `dom-${test.execution_id}-${st.step_id}.html`)}>
                      <FileCode2 size={14} /> Page HTML at this step
                    </button>
                  )}
                </div>
              )}
              {(st.console?.length > 0 || st.network_errors?.length > 0) && (
                <details className="small">
                  <summary>Console and network ({(st.console?.length || 0) + (st.network_errors?.length || 0)})</summary>
                  <ul className="plain-list mono xsmall">
                    {[...(st.console || []), ...(st.network_errors || [])].map((m, j) => <li key={j} className="cell-wrap">{m}</li>)}
                  </ul>
                </details>
              )}
            </li>
          ))}
        </ol>
      ) : (
        <div className="empty">
          <span className="empty-title">No step details for this execution</span>
          It ran before step recording was added, or the browser could not start.
          {ex.error_message && <span className="small cell-wrap">{ex.error_message}</span>}
        </div>
      ))}
    </section>
  );
}

export default function RunDetail({ params, onNavigate }) {
  const { testCases, refresh } = useWorkspace();
  const [runId, execParam] = String(params?.tab || '').split('/');
  const [run, setRun] = useState(null);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);
  const selectedExec = Number(execParam) || null;

  useEffect(() => {
    let alive = true;
    let timer = null;
    const pull = () => getPipelineRun(runId)
      .then((r) => {
        if (!alive) return;
        setRun(r);
        if (ACTIVE.includes(r.status)) timer = setTimeout(pull, 2000);
      })
      .catch((err) => alive && setError(err.message));
    setRun(null);
    setError(null);
    pull();
    return () => { alive = false; clearTimeout(timer); };
  }, [runId]);

  const open = (execId) => onNavigate('runs', { tab: execId ? `${runId}/${execId}` : runId });

  async function quarantine(test, value) {
    await updateTestCase(test.test_case_id, { quarantined: value });
    setRun((r) => ({ ...r, tests: r.tests.map((t) => (t.test_case_id === test.test_case_id ? { ...t, quarantined: value } : t)) }));
    refresh();
  }

  function copyLink() {
    navigator.clipboard?.writeText(window.location.href).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }).catch(() => {});
  }

  if (error) {
    return (
      <div className="page">
        <section className="card">
          <div className="empty">
            <span className="empty-title">Run #{runId} is not available</span>
            {error}
            <button type="button" className="btn btn-sm" onClick={() => onNavigate('autopilot')}>Back to Autopilot</button>
          </div>
        </section>
      </div>
    );
  }
  if (!run) return <div className="page"><section className="card"><Skeleton lines={6} block /></section></div>;

  const s = run.summary;
  const tests = run.tests || [];
  const quarantinedIds = new Set(testCases.filter((t) => t.quarantined).map((t) => t.id));
  const withState = tests.map((t) => ({ ...t, quarantined: t.quarantined ?? quarantinedIds.has(t.test_case_id) }));
  const selected = withState.find((t) => t.execution_id === selectedExec) || null;

  return (
    <div className="page">
      <div>
        <button type="button" className="btn btn-sm btn-ghost" onClick={() => onNavigate('autopilot')}><ArrowLeft size={14} /> Autopilot</button>
      </div>
      <div className="page-title">
        <div>
          <h1>Run #{run.id} · {run.project_name}</h1>
          <p className="row">
            <RunStatus status={run.status} />
            <span>{TRIGGER_LABEL[run.trigger] || run.trigger}{run.trigger_detail ? ` · ${run.trigger_detail}` : ''}</span>
            <span className="muted" title={toDate(run.started_at || run.created_at).toLocaleString()}>{timeAgo(run.finished_at || run.started_at || run.created_at)}</span>
            {run.actor && <span className="muted">by {run.actor}</span>}
          </p>
        </div>
        <div className="page-actions">
          <button type="button" className="btn" onClick={copyLink}><Link2 size={16} /> {copied ? 'Link copied' : 'Copy link'}</button>
        </div>
      </div>

      {run.error && <div className="alert-banner inline cell-wrap">{run.error}</div>}

      <ol className="stage-list" aria-label="Stages">
        {run.stages.map((st) => (
          <li key={st.key} className={`stage-item ${st.status}`}>
            <StageIcon status={st.status} />
            <div className="min-w-0">
              <div className="stage-label">{st.label}</div>
              {st.detail && <div className="small muted cell-wrap">{st.detail}</div>}
            </div>
          </li>
        ))}
      </ol>

      {s && (
        <div className="stat-tiles">
          <div className="stat-tile"><div className="v">{s.passed}/{s.total}</div><div className="l">Tests passed</div></div>
          <div className="stat-tile"><div className={`v ${s.failed ? 'bad' : ''}`}>{s.failed}</div><div className="l">Failed{s.quarantined_failed ? ` (+${s.quarantined_failed} quarantined)` : ''}</div></div>
          <div className="stat-tile"><div className="v">{s.healed}</div><div className="l">Self-healed</div></div>
          <div className="stat-tile"><div className="v">{s.flaky ?? 0}</div><div className="l">Flaky</div></div>
          <div className="stat-tile"><div className="v">{(run.regressions || []).length}</div><div className="l">Regressions</div></div>
          <div className="stat-tile"><div className="v">{s.findings ? Object.values(s.findings).reduce((a, b) => a + b, 0) : '—'}</div><div className="l">Security findings</div></div>
        </div>
      )}

      <div className={selected ? 'grid-side-main' : ''}>
        <section className="card">
          <div className="card-head"><h3>Tests</h3><span className="muted small">{tests.length}</span></div>
          {tests.length === 0 ? <div className="empty">{ACTIVE.includes(run.status) ? 'Tests appear here as they run.' : 'This run did not reach test execution.'}</div> : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Test</th><th>Result</th>{!selected && <th>Details</th>}</tr></thead>
                <tbody>
                  {withState.map((t) => (
                    <tr key={t.execution_id} className={`selectable ${t.execution_id === selectedExec ? 'selected' : ''}`}
                      {...selectableRow(() => open(t.execution_id === selectedExec ? null : t.execution_id), t.execution_id === selectedExec)}>
                      <td className="cell-wrap">{t.name}<div className="small muted">{t.category || 'saved'} · #{t.execution_id}</div></td>
                      <td>
                        <div className="row">
                          <span className={`status ${testLabel(t)}`}>{testLabel(t)}</span>
                          {t.flaky && <span className="status FLAKY">Flaky</span>}
                          {t.quarantined && <span className="pill gray">Quarantined</span>}
                        </div>
                      </td>
                      {!selected && <td className="small cell-wrap">{t.error ? t.error.split('\n')[0] : '—'}</td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
        {selected && <ExecutionDetail key={selected.execution_id} test={selected} onQuarantine={quarantine} />}
      </div>

      {(run.regressions || []).length > 0 && (
        <section className="card">
          <div className="card-head"><h3>Regressions</h3><span className="muted small">since run #{s?.previous_run_id}</span></div>
          <ul className="plain-list">
            {run.regressions.map((r, i) => (
              <li key={i} className="small cell-wrap"><span className="sev high">{r.kind}</span> {r.name}: {r.was} → <b>{r.now}</b>{r.error ? ` · ${r.error.split('\n')[0]}` : ''}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
