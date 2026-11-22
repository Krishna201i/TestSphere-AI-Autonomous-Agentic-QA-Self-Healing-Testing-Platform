import React, { useMemo, useState } from 'react';
import { CirclePlay } from 'lucide-react';
import { useWorkspace } from '../state/Workspace';
import { formatDuration, pct, timeAgo, toDate } from '../lib/derive';
import { runPassRate } from '../lib/dashboard';
import { usePaged } from '../lib/usePaged';
import Pager from '../components/Pager';
import { RunStatus, TRIGGER_LABEL } from './Autopilot';

const FILTERS = [['all', 'All'], ['active', 'Running'], ['passed', 'Passed'], ['failed', 'Failed']];

function duration(run) {
  const start = toDate(run.started_at);
  const end = toDate(run.finished_at);
  return start && end ? formatDuration(end - start) : '—';
}

export default function TestRuns({ onNavigate }) {
  const ws = useWorkspace();
  const pipelineRuns = ws.pipelineRuns || []; // null while loading
  const projects = ws.projects || [];
  const [filter, setFilter] = useState('all');
  const [project, setProject] = useState('');
  const runs = useMemo(() => pipelineRuns.filter((r) => {
    if (project && String(r.project_id) !== project) return false;
    if (filter === 'active') return ['queued', 'running'].includes(r.status);
    if (filter === 'passed') return r.status === 'passed';
    if (filter === 'failed') return ['failed', 'error'].includes(r.status);
    return true;
  }), [pipelineRuns, filter, project]);
  const paged = usePaged(runs, 15);

  return (
    <div className="page">
      <div className="page-title">
        <div>
          <h1>Test Runs</h1>
          <p>Every pipeline run: what started it, how many tests passed, healed or failed, and how long it took.</p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => onNavigate('autopilot')}><CirclePlay size={16} /> Run the pipeline</button>
      </div>

      <section className="card">
        <div className="row-between">
          <div className="tabs" role="tablist" aria-label="Filter runs">
            {FILTERS.map(([id, label]) => (
              <button key={id} type="button" role="tab" aria-selected={filter === id} className={`tab ${filter === id ? 'active' : ''}`}
                onClick={() => setFilter(id)}>{label}</button>
            ))}
          </div>
          <label className="field">
            <span className="visually-hidden">Project</span>
            <select className="input" value={project} onChange={(e) => setProject(e.target.value)} aria-label="Project">
              <option value="">All projects</option>
              {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
        </div>

        {runs.length === 0 ? (
          <div className="empty">
            <span className="empty-title">{pipelineRuns.length ? 'No runs match' : 'No runs yet'}</span>
            {!pipelineRuns.length && 'Run the pipeline on your site in Projects; every run is listed here.'}
          </div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Run</th><th>Project</th><th>Status</th><th>Trigger</th><th className="num">Tests</th><th className="num">Passed</th><th>Duration</th><th>Started</th></tr>
              </thead>
              <tbody>
                {paged.items.map((r) => {
                  const s = r.summary || {};
                  return (
                    <tr key={r.id} className="selectable" tabIndex={0} onClick={() => onNavigate('runs', { tab: String(r.id) })}
                      onKeyDown={(e) => { if (e.key === 'Enter') onNavigate('runs', { tab: String(r.id) }); }}
                      aria-label={`Open run ${r.id}`}>
                      <td className="mono">#{r.id}</td>
                      <td>{r.project_name}</td>
                      <td><RunStatus status={r.status} /></td>
                      <td>{TRIGGER_LABEL[r.trigger] || r.trigger}</td>
                      <td className="num">{s.total ?? '—'}</td>
                      <td className="num">
                        {s.total ? pct(runPassRate(r), 0) : '—'}
                        {s.healed ? <div className="hint">{s.healed} healed</div> : null}
                        {s.failed ? <div className="hint bad-text">{s.failed} failed</div> : null}
                      </td>
                      <td>{duration(r)}</td>
                      <td>{timeAgo(r.started_at || r.created_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <Pager paged={paged} label="runs" />
      </section>
    </div>
  );
}
