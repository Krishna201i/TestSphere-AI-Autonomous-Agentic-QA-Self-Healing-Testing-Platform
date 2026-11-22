import React, { useState } from 'react';
import { useWorkspace } from '../state/Workspace';
import { updateProject } from '../services/api';
import { timeAgo, timeUntil } from '../lib/derive';
import { RunStatus, SCHEDULES } from './Autopilot';

export default function Schedules({ onNavigate }) {
  const { system, refresh, ...ws } = useWorkspace();
  const projects = ws.projects || []; // null while loading
  const pipelineRuns = ws.pipelineRuns || [];
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const lastRun = (p) => pipelineRuns.find((r) => r.project_id === p.id) || null;
  const schedulerOff = system?.scheduler && !system.scheduler.enabled && !system.scheduler.external_tick;

  async function setSchedule(project, value) {
    setBusy(project.id);
    setError(null);
    try {
      await updateProject(project.id, { schedule_minutes: value ? Number(value) : null });
      await refresh?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="page">
      <div className="page-title">
        <div>
          <h1>Schedules</h1>
          <p>Re-run each project's pipeline on a timer. Every scheduled run tests, heals and scans like a manual one.</p>
        </div>
      </div>
      {schedulerOff && (
        <div className="alert-banner inline" role="status">
          The scheduler is turned off on this server (SCHEDULER_ENABLED=false): schedules are saved but will not fire.
        </div>
      )}
      {error && <div className="alert-banner inline" role="alert">{error}</div>}
      <section className="card">
        {projects.length === 0 ? (
          <div className="empty">
            <span className="empty-title">No projects yet</span>
            Run the pipeline on your site once; then schedule it here.
            <button type="button" className="btn btn-sm" onClick={() => onNavigate('autopilot')}>Open Projects</button>
          </div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Project</th><th>Runs</th><th>Next run</th><th>Last run</th></tr></thead>
              <tbody>
                {projects.map((p) => {
                  const last = lastRun(p);
                  return (
                    <tr key={p.id}>
                      <td><b>{p.name}</b><div className="hint mono">{p.app_url || 'No site URL'}</div></td>
                      <td>
                        <select className="input" aria-label={`Schedule for ${p.name}`} value={p.schedule_minutes || ''}
                          disabled={busy === p.id || !p.app_url} onChange={(e) => setSchedule(p, e.target.value)}>
                          {SCHEDULES.map(([v, l]) => <option key={l} value={v || ''}>{l}</option>)}
                        </select>
                      </td>
                      <td>{p.schedule_minutes && p.next_run_at ? timeUntil(p.next_run_at) : <span className="muted">—</span>}</td>
                      <td>
                        {last ? (
                          <button type="button" className="btn btn-sm btn-ghost" onClick={() => onNavigate('runs', { tab: String(last.id) })}>
                            <RunStatus status={last.status} /> #{last.id} · {timeAgo(last.created_at)}
                          </button>
                        ) : <span className="muted">Never</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
