import React, { useEffect, useMemo, useState } from 'react';
import {
  CheckCircle2, Circle, Copy, Database, GitBranch, Loader2, MinusCircle, Play, RefreshCw, Rocket, Unplug, XCircle, Zap,
} from 'lucide-react';
import { useWorkspace } from '../state/Workspace';
import {
  deployProject,
  getPipelineRun,
  getProjectDatabase,
  linkProjectDatabase,
  quickPipeline,
  rotateWebhookSecret,
  runProjectPipeline,
  unlinkProjectDatabase,
  updateProject,
  webhookUrl,
} from '../services/api';
import { timeAgo, timeUntil, urlError } from '../lib/derive';
import { selectableRow } from '../lib/a11y';

const SCHEDULES = [
  [null, 'Off'], [15, 'Every 15 min'], [30, 'Every 30 min'], [60, 'Hourly'], [180, 'Every 3 hours'],
  [360, 'Every 6 hours'], [720, 'Every 12 hours'], [1440, 'Daily'], [10080, 'Weekly'],
];
const TRIGGER_LABEL = { manual: 'Manual', schedule: 'Scheduled', webhook: 'GitHub push' };
const ACTIVE = ['queued', 'running'];

export function StageIcon({ status }) {
  if (status === 'done') return <CheckCircle2 size={18} className="ok-text" />;
  if (status === 'failed') return <XCircle size={18} className="bad-text" />;
  if (status === 'running') return <Loader2 size={18} className="spin" />;
  if (status === 'skipped') return <MinusCircle size={18} className="muted" />;
  return <Circle size={18} className="muted" />;
}

export function RunStatus({ status }) {
  return <span className={`status run-${status}`}>{status}</span>;
}

function QuickRun({ onStarted }) {
  const [form, setForm] = useState({ url: '', prompt: '', repo_url: '' });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e) {
    e.preventDefault();
    setError(null);
    const bad = urlError(form.url);
    if (bad) {
      setError(bad);
      return;
    }
    setBusy(true);
    try {
      const run = await quickPipeline({
        url: form.url.trim(), prompt: form.prompt.trim() || null, repo_url: form.repo_url.trim() || null,
      });
      onStarted(run);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <div className="card-head"><h3>Run the whole pipeline</h3><span className="pill violet"><Zap size={14} /> One click</span></div>
      <p className="card-sub">
        Analyzes the page, plans a suite of tests, runs every one in a real browser, self-heals broken steps,
        scans security headers and reports regressions — no manual steps. The URL becomes a project you can schedule below.
      </p>
      <form className="form-row" onSubmit={onSubmit}>
        <label className="field wide">
          Target URL
          <input className="input" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder="https://your-app.example/" required />
        </label>
        <label className="field wide">
          What to test (optional)
          <input className="input" value={form.prompt} onChange={(e) => setForm({ ...form, prompt: e.target.value })} placeholder="e.g. log in and reach the dashboard" />
        </label>
        <label className="field">
          Git repository (optional)
          <input className="input" value={form.repo_url} onChange={(e) => setForm({ ...form, repo_url: e.target.value })} placeholder="https://github.com/you/app" />
        </label>
        <button className="btn btn-primary" type="submit" disabled={busy}><Play size={16} /> {busy ? 'Starting…' : 'Run pipeline'}</button>
      </form>
      {error && <div className="error-text">{error}</div>}
    </section>
  );
}

function RunDetail({ run, onOpen }) {
  if (!run) {
    return (
      <section className="card">
        <div className="card-head"><h3>Pipeline run</h3></div>
        <div className="empty">No runs yet. Start one above, or turn on a schedule for a project.</div>
      </section>
    );
  }
  const s = run.summary;
  return (
    <section className="card">
      <div className="card-head">
        <h3>Run #{run.id} · {run.project_name}</h3>
        <span className="row"><RunStatus status={run.status} /> <span className="muted small">{TRIGGER_LABEL[run.trigger] || run.trigger}{run.trigger_detail ? ` · ${run.trigger_detail}` : ''} · {timeAgo(run.started_at || run.created_at)}</span></span>
      </div>
      <div className="row">
        <button type="button" className="btn btn-sm" onClick={() => onOpen(run.id)}>Open run: steps, screenshots and trace</button>
      </div>
      {run.error && <div className="subbox small cell-wrap bad-text">{run.error}</div>}

      <ol className="stage-list">
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
          <div className="stat-tile"><div className="v">{s.failed}</div><div className="l">Failed</div></div>
          <div className="stat-tile"><div className="v">{s.healed}</div><div className="l">Self-healed</div></div>
          <div className="stat-tile"><div className="v">{s.findings ? Object.values(s.findings).reduce((a, b) => a + b, 0) : '—'}</div><div className="l">Security findings</div></div>
          <div className="stat-tile"><div className="v">{(run.regressions || []).length}</div><div className="l">Regressions</div></div>
        </div>
      )}

      {(run.regressions || []).length > 0 && (
        <div className="subbox">
          <h4>Regressions since run #{s?.previous_run_id}</h4>
          <ul className="plain-list">
            {run.regressions.map((r, i) => (
              <li key={i} className="small cell-wrap"><span className="sev high">{r.kind}</span> {r.name}: {r.was} → <b>{r.now}</b>{r.error ? ` — ${r.error.split('\n')[0]}` : ''}</li>
            ))}
          </ul>
        </div>
      )}

      {(run.tests || []).length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Test</th><th>Result</th><th>Details</th></tr></thead>
            <tbody>
              {run.tests.map((t) => (
                <tr key={t.execution_id} className="selectable" {...selectableRow(() => onOpen(run.id, t.execution_id), false)}>
                  <td className="cell-wrap">{t.name}<div className="small muted">{t.category || 'saved'} · execution #{t.execution_id}</div></td>
                  <td><span className="row"><span className={`status ${t.healed && t.status === 'PASSED' ? 'HEALED' : t.status}`}>{t.healed && t.status === 'PASSED' ? 'HEALED' : t.status}</span>{t.flaky && <span className="status FLAKY">Flaky</span>}</span></td>
                  <td className="small cell-wrap">{t.error ? t.error.split('\n')[0] : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function CopyField({ label, value }) {
  const [copied, setCopied] = useState(false);
  return (
    <label className="field">
      {label}
      <span className="copy-field">
        <input className="input mono small" readOnly value={value} onFocus={(e) => e.target.select()} />
        <button type="button" className="btn btn-sm" onClick={() => {
          navigator.clipboard?.writeText(value).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }).catch(() => {});
        }}><Copy size={13} /> {copied ? 'Copied' : 'Copy'}</button>
      </span>
    </label>
  );
}

/** The app's database as a read-only input: runs report what the tests changed in it. */
function ProjectDatabase({ project, onChanged }) {
  const [info, setInfo] = useState(null);
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!project.database) {
      setInfo({ connected: false, tables: [] });
      return;
    }
    getProjectDatabase(project.id).then(setInfo).catch((err) => setError(err.message));
  }, [project.id, project.database]);

  async function act(fn) {
    setBusy(true);
    setError(null);
    try {
      setInfo(await fn());
      setUrl('');
      onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="form-stack">
      <h4 className="section-title"><Database size={14} className="icon-inline" /> App database (read-only)</h4>
      {info?.connected ? (
        <>
          <div className="small">
            <b>{info.database}</b>
            {info.checked_at && <span className="muted"> · schema read {timeAgo(info.checked_at)}</span>}
          </div>
          {info.tables?.length > 0 && (
            <ul className="plain-list small">
              {info.tables.slice(0, 12).map((t) => (
                <li key={t.name}><span className="mono">{t.name}</span> <span className="muted">· {t.rows} row(s) · {t.columns.length} column(s)</span></li>
              ))}
              {info.tables.length > 12 && <li className="muted">and {info.tables.length - 12} more</li>}
            </ul>
          )}
          <p className="hint m-0">Each run reports which rows its tests added or changed, and whether your goal's values were stored.</p>
          <div>
            <button type="button" className="btn btn-sm btn-ghost" disabled={busy}
              onClick={() => act(async () => { await unlinkProjectDatabase(project.id); return { connected: false, tables: [] }; })}>
              <Unplug size={13} /> Unlink
            </button>
          </div>
        </>
      ) : (
        <form className="form-stack" onSubmit={(e) => { e.preventDefault(); act(() => linkProjectDatabase(project.id, url.trim())); }}>
          <p className="hint m-0">
            Link the database your app writes to and each run reports what its tests changed there. Use a read-only user;
            the URL is stored encrypted and never shown again.
          </p>
          <label className="field">
            Connection URL
            <input className="input mono" type="password" value={url} onChange={(e) => setUrl(e.target.value)} autoComplete="off"
              spellCheck={false} placeholder="postgresql://reader:password@host:5432/app" minLength={10} required />
          </label>
          <div><button type="submit" className="btn btn-sm" disabled={busy || url.trim().length < 10}>{busy ? 'Connecting…' : 'Link database'}</button></div>
        </form>
      )}
      {error && <div className="error-text" role="alert">{error}</div>}
    </div>
  );
}

function ProjectRow({ project, latest, onRun, onChanged, onDeployed }) {
  const [open, setOpen] = useState(false);
  const fromProject = (p) => ({
    app_url: p.app_url || '', repo_url: p.repo_url || '', prompt: p.prompt || '',
    slack_webhook_url: p.slack_webhook_url || '', notify_on: p.notify_on || 'failures',
    deploy_hook_url: p.deploy_hook_url || '', rollback_hook_url: p.rollback_hook_url || '',
    health_url: p.health_url || '', deploy_on_pass: Boolean(p.deploy_on_pass),
    sign_in_first: Boolean(p.sign_in_first),
  });
  const [form, setForm] = useState(() => fromProject(project));
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setForm(fromProject(project));
  }, [project.app_url, project.repo_url, project.prompt, project.slack_webhook_url, project.notify_on,
    project.deploy_hook_url, project.rollback_hook_url, project.health_url, project.deploy_on_pass,
    project.sign_in_first]); // eslint-disable-line react-hooks/exhaustive-deps

  async function act(fn) {
    setError(null);
    setBusy(true);
    try {
      await fn();
      onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const active = latest && ACTIVE.includes(latest.status);
  return (
    <>
      <tr>
        <td className="cell-wrap"><b>{project.name}</b><div className="small muted mono">{project.app_url || 'no app URL'}</div></td>
        <td>
          <select className="input select-sm" aria-label={`Schedule for ${project.name}`} value={project.schedule_minutes || ''} disabled={busy || !project.app_url}
            onChange={(e) => act(() => updateProject(project.id, { schedule_minutes: e.target.value ? Number(e.target.value) : null }))}>
            {SCHEDULES.map(([v, l]) => <option key={l} value={v || ''}>{l}</option>)}
          </select>
          {project.next_run_at && <div className="small muted">next run {timeUntil(project.next_run_at)}</div>}
        </td>
        <td>{latest ? <RunStatus status={latest.status} /> : project.last_run_status ? <RunStatus status={project.last_run_status} /> : <span className="muted small">never run</span>}</td>
        <td className="text-right nowrap">
          <button type="button" className="btn btn-sm" onClick={() => setOpen(!open)} aria-expanded={open}>Settings</button>{' '}
          {project.deploy_hook_url && (
            <>
              <button type="button" className="btn btn-sm" disabled={busy} title="Deploy, check health and smoke tests, roll back on failure"
                onClick={() => act(async () => { await deployProject(project.id); onDeployed(); })}>
                <Rocket size={13} /> Deploy
              </button>{' '}
            </>
          )}
          <button type="button" className="btn btn-sm btn-primary" disabled={busy || active || !project.app_url}
            onClick={() => act(async () => onRun(await runProjectPipeline(project.id)))}>
            <Play size={13} /> {active ? latest.status : 'Run now'}
          </button>
        </td>
      </tr>
      {(open || error) && (
        <tr className="row-detail">
          <td colSpan={4}>
            {open && (
              <div className="settings-grid">
                <form className="form-stack" onSubmit={(e) => { e.preventDefault(); act(() => updateProject(project.id, form)); }}>
                  <label className="field">App URL<input className="input" value={form.app_url} onChange={(e) => setForm({ ...form, app_url: e.target.value })} placeholder="https://app.example/" /></label>
                  <label className="field">Git repository<input className="input" value={form.repo_url} onChange={(e) => setForm({ ...form, repo_url: e.target.value })} placeholder="https://github.com/you/app" /></label>
                  <label className="field">What to test<input className="input" value={form.prompt} onChange={(e) => setForm({ ...form, prompt: e.target.value })} placeholder="optional" /></label>
                  <label className="check">
                    <input type="checkbox" checked={form.sign_in_first}
                      onChange={(e) => setForm({ ...form, sign_in_first: e.target.checked })} />
                    Sign in first: run the goal&apos;s login test, then test linked pages signed in (for example “log in with demo / secret”)
                  </label>
                  <label className="field">
                    Chat alerts (Slack, Discord, Google Chat or Teams webhook URL)
                    <input className="input" value={form.slack_webhook_url} onChange={(e) => setForm({ ...form, slack_webhook_url: e.target.value })}
                      placeholder="https://hooks.slack.com/services/… or https://discord.com/api/webhooks/…" />
                  </label>
                  <label className="field">
                    Send an alert
                    <select className="input" value={form.notify_on} onChange={(e) => setForm({ ...form, notify_on: e.target.value })} disabled={!form.slack_webhook_url}>
                      <option value="failures">When a run fails or regresses</option>
                      <option value="always">After every run</option>
                    </select>
                  </label>
                  <h4 className="section-title mt-3">Verified deploy</h4>
                  <label className="field">
                    Deploy hook (Render, Vercel or Netlify)
                    <input className="input" value={form.deploy_hook_url} onChange={(e) => setForm({ ...form, deploy_hook_url: e.target.value })}
                      placeholder="https://api.render.com/deploy/srv-…?key=…" />
                  </label>
                  <label className="field">
                    Rollback hook (optional; on Render the last verified commit is redeployed)
                    <input className="input" value={form.rollback_hook_url} onChange={(e) => setForm({ ...form, rollback_hook_url: e.target.value })}
                      placeholder="A deploy hook for your stable version" />
                  </label>
                  <label className="field">
                    Health URL (default: the app URL)
                    <input className="input" value={form.health_url} onChange={(e) => setForm({ ...form, health_url: e.target.value })}
                      placeholder="https://app.example/health" />
                  </label>
                  <label className="check">
                    <input type="checkbox" checked={form.deploy_on_pass} disabled={!form.deploy_hook_url}
                      onChange={(e) => setForm({ ...form, deploy_on_pass: e.target.checked })} />
                    Deploy and verify automatically after a run passes with no regressions
                  </label>
                  <div><button type="submit" className="btn btn-sm" disabled={busy}>Save</button></div>
                </form>
                <div className="form-stack">
                  <div className="small"><GitBranch size={14} className="icon-inline" /> <b>Run on every push</b> — in GitHub: Settings → Webhooks → Add webhook, content type <span className="mono">application/json</span>, “Just the push event”.</div>
                  <CopyField label="Payload URL" value={webhookUrl(project.id)} />
                  <CopyField label="Secret" value={project.webhook_secret || ''} />
                  <div><button type="button" className="btn btn-sm" disabled={busy} onClick={() => act(() => rotateWebhookSecret(project.id))}><RefreshCw size={13} /> New secret</button></div>
                  <ProjectDatabase project={project} onChanged={onChanged} />
                </div>
              </div>
            )}
            {error && <div className="error-text">{error}</div>}
          </td>
        </tr>
      )}
    </>
  );
}

export default function Autopilot({ onNavigate }) {
  const { projects, refresh, system, pipelineRuns, refreshRuns, refreshDeployments } = useWorkspace();
  const runs = pipelineRuns || [];
  const [selectedId, setSelectedId] = useState(null);
  const [older, setOlder] = useState(null); // a run past the list's newest 40

  // The list holds full records and is followed every 2 seconds while a run is active
  const shownId = selectedId || runs[0]?.id || null;
  const listed = runs.find((r) => r.id === shownId) || null;
  useEffect(() => {
    if (!shownId || listed) return;
    getPipelineRun(shownId).then(setOlder).catch(() => setOlder(null));
  }, [shownId, listed]);
  const shown = listed || (older?.id === shownId ? older : null);

  const latestByProject = useMemo(() => {
    const map = {};
    for (const r of runs) if (!map[r.project_id]) map[r.project_id] = r;
    return map;
  }, [runs]);

  function started(run) {
    setSelectedId(run.id);
    refreshRuns();
    refresh();
  }

  return (
    <div className="page">
      <div className="page-title">
        <div>
          <h1>Autopilot</h1>
          <p>One pipeline from URL to report: codebase ingestion → page analysis → test planning → execution → self-healing → security scan → regression report. Run it on demand, on a schedule, or on every GitHub push.</p>
        </div>
      </div>

      <QuickRun onStarted={started} />
      <RunDetail run={shown} onOpen={(id, exec) => onNavigate('runs', { tab: exec ? `${id}/${exec}` : String(id) })} />

      <section className="card">
        <div className="card-head"><h3>Projects</h3><span className="muted small">{projects.length}</span></div>
        {system?.scheduler && !system.scheduler.enabled && (
          <div className="hint">The scheduler is turned off on this server (SCHEDULER_ENABLED=false); schedules are saved but will not fire.</div>
        )}
        {projects.length === 0 ? <div className="empty">No projects yet — run the pipeline on a URL above.</div> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Project</th><th>Schedule</th><th>Last run</th><th /></tr></thead>
              <tbody>
                {projects.map((p) => (
                  <ProjectRow key={p.id} project={p} latest={latestByProject[p.id]} onRun={started} onChanged={refresh}
                    onDeployed={() => { refreshDeployments(); onNavigate('validation'); }} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <div className="card-head"><h3>Run history</h3><span className="muted small">{runs.length}</span></div>
        {runs.length === 0 ? <div className="empty">Nothing has run yet.</div> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Run</th><th>Project</th><th>Trigger</th><th>Status</th><th>Result</th><th>When</th></tr></thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id} className={`selectable ${r.id === shownId ? 'selected' : ''}`} {...selectableRow(() => setSelectedId(r.id), r.id === shownId)}>
                    <td>#{r.id}</td>
                    <td className="cell-wrap">{r.project_name}</td>
                    <td className="small">{TRIGGER_LABEL[r.trigger] || r.trigger}</td>
                    <td><RunStatus status={r.status} /></td>
                    <td className="small">{r.summary ? `${r.summary.passed}/${r.summary.total} passed${r.regressions?.length ? ` · ${r.regressions.length} regression(s)` : ''}` : (r.error ? r.error.slice(0, 60) : '—')}</td>
                    <td className="small muted">{timeAgo(r.finished_at || r.started_at || r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
