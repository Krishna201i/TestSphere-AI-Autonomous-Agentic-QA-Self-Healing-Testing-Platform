import React, { useState } from 'react';
import { Play } from 'lucide-react';
import { useWorkspace } from '../state/Workspace';
import { loopModel, timeAgo, toDate, urlError } from '../lib/derive';
import { selectableRow } from '../lib/a11y';
import LoopPanel from '../components/PipelineLoop';
import CodebaseIngestion from '../components/CodebaseIngestion';

const BUILT_LABEL = { built: 'Built', partial: 'Partly built', planned: 'Planned' };
const BUILT_TONE = { built: 'green', partial: 'orange', planned: 'gray' };
const STATE_LABEL = {
  running: 'Running', done: 'Done', failed: 'Failed', waiting: 'Needs you', skipped: 'Skipped', pending: 'Queued', idle: 'Ready', planned: 'Not built',
};
const STEP_STATUS = { passed: 'PASSED', failed: 'FAILED', healed: 'HEALED' };

function RunQA() {
  const { runPipeline, running, applications } = useWorkspace();
  const [url, setUrl] = useState('');
  const [prompt, setPrompt] = useState('');
  const [error, setError] = useState(null);

  async function onRun(e) {
    e.preventDefault();
    setError(null);
    const bad = urlError(url);
    if (bad) {
      setError(bad);
      return;
    }
    try {
      await runPipeline({ app_url: url.trim(), prompt: prompt.trim() || null }, url.trim());
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <section className="card">
      <div className="card-head"><h3>Run one QA test</h3><span className="pill blue">2A · AI QA Agent</span></div>
      <p className="card-sub">Plans and runs a single test on a page. For the whole loop, with security and reports, use Autopilot.</p>
      <form className="form-row" onSubmit={onRun}>
        <label className="field wide">
          Target URL
          <input className="input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://your-app.example/" required />
        </label>
        <label className="field wide">
          What to test (optional)
          <input className="input" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="e.g. log in and reach the dashboard" />
        </label>
        <button className="btn btn-primary" type="submit" disabled={Boolean(running)}>
          <Play size={16} /> {running ? 'Running…' : 'Plan and run'}
        </button>
      </form>
      {applications.length > 0 && (
        <div className="row small">
          <span className="muted">Saved targets:</span>
          {applications.slice(0, 6).map((a) => (
            <button key={a.id} type="button" className="chip" onClick={() => setUrl(a.base_url)}>{a.name}</button>
          ))}
        </div>
      )}
      {running && <div className="hint">Analyzing the page, planning steps and running them in Playwright: {running}</div>}
      {error && <div className="error-text">{error}</div>}
    </section>
  );
}

function LastRun() {
  const { lastRun } = useWorkspace();
  if (!lastRun) return null;
  const steps = lastRun.engine_steps || [];
  return (
    <section className="card">
      <div className="card-head">
        <h3>Last run</h3>
        <span><span className={`status ${lastRun.status}`}>{lastRun.status}</span> <span className="muted small">{lastRun.label} · {timeAgo(lastRun.at)}</span></span>
      </div>
      {lastRun.error_message && <div className="subbox mono small cell-wrap">{lastRun.error_message}</div>}
      <div className="grid-2">
        <div>
          <h4 className="section-title">Engine steps</h4>
          {steps.length === 0 ? <div className="empty">No step results returned.</div> : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Step</th><th>Status</th><th>Locator</th><th>ms</th></tr></thead>
                <tbody>
                  {steps.map((s) => (
                    <tr key={s.step_id}>
                      <td className="small">{s.step_id}</td>
                      <td><span className={`status ${STEP_STATUS[s.status] || ''}`}>{s.status}</span></td>
                      <td className="mono small cell-wrap">{s.locator_used || '—'}{s.healing?.selected_locator ? ` (healed from ${s.healing.original_locator})` : ''}{s.error && s.status === 'failed' ? <div className="error-text small">{s.error.split('\n')[0]}</div> : null}</td>
                      <td className="small">{s.duration_ms}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        <div>
          <h4 className="section-title">Agent events</h4>
          {(lastRun.events || []).length === 0 ? <div className="empty">No agent events.</div> : (
            <ul className="timeline">
              {lastRun.events.map((ev, i) => (
                <li key={i}>
                  <span className="when">{toDate(ev.timestamp).toLocaleTimeString()}</span>
                  <span className="mark info" />
                  <span><span className="kind">{ev.event_type}</span>{ev.message}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}

function Targets() {
  const { applications, projects, addTarget } = useWorkspace();
  const [form, setForm] = useState({ projectName: projects[0]?.name || 'TestSphere Auto QA', appName: '', baseUrl: '' });
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const projectName = (id) => projects.find((p) => p.id === id)?.name || `#${id}`;

  async function onAdd(e) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      await addTarget(form);
      setForm((f) => ({ ...f, appName: '', baseUrl: '' }));
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="card">
      <div className="card-head"><h3>Targets</h3><span className="muted small">{applications.length}</span></div>
      <p className="card-sub">Running apps to test, by base URL. Analyze their source in Codebase Ingestion above.</p>
      {applications.length === 0 ? <div className="empty">No targets yet.</div> : (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Application</th><th>URL</th><th>Project</th></tr></thead>
            <tbody>
              {applications.map((a) => (
                <tr key={a.id}><td>{a.name}</td><td className="mono small cell-wrap">{a.base_url}</td><td className="small">{projectName(a.project_id)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <form className="form-row" onSubmit={onAdd}>
        <input className="input" value={form.projectName} onChange={(e) => setForm({ ...form, projectName: e.target.value })} placeholder="Project" required aria-label="Project name" />
        <input className="input" value={form.appName} onChange={(e) => setForm({ ...form, appName: e.target.value })} placeholder="Application name" required aria-label="Application name" />
        <input className="input" value={form.baseUrl} onChange={(e) => setForm({ ...form, baseUrl: e.target.value })} placeholder="https://app.example/" required type="url" aria-label="Base URL" />
        <button className="btn" type="submit" disabled={saving}>{saving ? 'Adding…' : 'Add target'}</button>
      </form>
      {error && <div className="error-text">{error}</div>}
    </section>
  );
}

function TestCases() {
  const { testCases, executions, runPipeline, running } = useWorkspace();
  const latest = (id) => executions.filter((e) => e.test_case_id === id).at(-1);
  return (
    <section className="card">
      <div className="card-head"><h3>Test cases</h3><span className="muted small">{testCases.length}</span></div>
      {testCases.length === 0 ? <div className="empty">No test cases yet — run the QA pipeline to plan one.</div> : (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Name</th><th>Last result</th><th /></tr></thead>
            <tbody>
              {[...testCases].reverse().map((tc) => {
                const ex = latest(tc.id);
                return (
                  <tr key={tc.id}>
                    <td className="cell-wrap">{tc.name}<div className="small muted">{tc.external_id || `#${tc.id}`}</div></td>
                    <td>{ex ? <span className={`status ${ex.status}`}>{ex.status}</span> : <span className="muted small">never run</span>}</td>
                    <td className="text-right">
                      <button type="button" className="btn btn-sm" disabled={Boolean(running)}
                        onClick={() => runPipeline({ test_case_id: tc.id }, tc.name).catch(() => {})}>
                        <Play size={13} /> Run
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default function PipelineVisualizer({ onNavigate }) {
  const ws = useWorkspace();
  const { stages, running } = loopModel(ws);
  return (
    <div className="page">
      <LoopPanel onNavigate={onNavigate} title="Pipeline Visualizer" />

      <section className="card">
        <div className="card-head"><h3>Stages</h3><span className="muted small">what each stage does and how much is built</span></div>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Stage</th><th>Now</th><th>Built</th><th>What it does</th></tr></thead>
            <tbody>
              {stages.map((s) => (
                <tr key={s.id} className={`selectable ${s.id === running?.id ? 'selected' : ''}`} {...selectableRow(() => onNavigate(s.page), s.id === running?.id)}>
                  <td className="nowrap"><span className="muted">{s.num}</span> <b>{s.title}</b></td>
                  <td className="nowrap small">{STATE_LABEL[s.state]}{s.note ? <div className="muted">{s.note}</div> : null}</td>
                  <td><span className={`pill ${BUILT_TONE[s.built]}`}>{BUILT_LABEL[s.built]}</span></td>
                  <td className="cell-wrap small">{s.about}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <CodebaseIngestion />
      <RunQA />
      <LastRun />
      <div className="grid-2">
        <Targets />
        <TestCases />
      </div>
    </div>
  );
}
