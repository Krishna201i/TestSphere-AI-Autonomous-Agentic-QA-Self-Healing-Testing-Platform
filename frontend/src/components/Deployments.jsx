/**
 * Verified deploys (loop stage 6): the newest deployment step by step, with
 * its health checks, and the ones before it.
 */
import React from 'react';
import { Rocket } from 'lucide-react';
import { useWorkspace } from '../state/Workspace';
import { DEPLOY_ACTIVE, DEPLOY_LABEL, timeAgo } from '../lib/derive';
import { Sparkline } from './charts';
import { StageIcon } from '../pages/Autopilot';

const TONE = { verified: 'run-passed', rolled_back: 'FLAKY', failed: 'run-failed', rollback_failed: 'run-failed', error: 'run-failed' };

export function DeployStatus({ status }) {
  return <span className={`status ${TONE[status] || 'run-running'}`}>{DEPLOY_LABEL[status] || status}</span>;
}

export default function Deployments({ onNavigate }) {
  const { deployments, projects } = useWorkspace();
  const latest = deployments[0];
  const configured = projects.some((p) => p.deploy_hook_url);
  return (
    <section className="card" aria-labelledby="deploy-title">
      <div className="card-head">
        <h3 id="deploy-title"><Rocket size={18} aria-hidden="true" />Verified deploy</h3>
        <span className="pill green">6 · Deploy</span>
      </div>
      {!latest ? (
        <div className="empty">
          <span className="empty-title">{configured ? 'No deployments yet' : 'Deploys are not set up'}</span>
          {configured
            ? 'Use Deploy on a project in Autopilot, or turn on deploying after passing runs.'
            : "Add your host's deploy hook (Render, Vercel or Netlify) to a project. TestSphere then deploys, checks health and smoke tests, and rolls back if they fail."}
          <button type="button" className="btn btn-sm" onClick={() => onNavigate('autopilot')}>Open Autopilot</button>
        </div>
      ) : (
        <>
          <div className="row-between">
            <span className="row">
              <DeployStatus status={latest.status} />
              <b>#{latest.id} · {latest.project_name}</b>
              {latest.commit && <span className="mono small">{latest.commit.slice(0, 7)}</span>}
            </span>
            <span className="small muted">{latest.trigger === 'pipeline' ? `after run #${latest.run_id}` : latest.trigger} · {timeAgo(latest.finished_at || latest.started_at || latest.created_at)}</span>
          </div>
          {latest.error && !DEPLOY_ACTIVE.includes(latest.status) && <div className="small bad-text cell-wrap">{latest.error}</div>}
          <ol className="stage-list" aria-label="Deployment steps">
            {latest.steps.map((st) => (
              <li key={st.key} className={`stage-item ${st.status}`}>
                <StageIcon status={st.status} />
                <div className="min-w-0">
                  <div className="stage-label">{st.label}</div>
                  {st.detail && <div className="small muted cell-wrap">{st.detail}</div>}
                </div>
              </li>
            ))}
          </ol>
          {latest.health?.length > 1 && (
            <div className="subbox tinted stack-sm">
              <span className="small">Health checks of the site during this deploy</span>
              <Sparkline samples={latest.health} />
            </div>
          )}
          {deployments.length > 1 && (
            <ul className="run-list">
              {deployments.slice(1, 6).map((d) => (
                <li key={d.id} className="run-link">
                  <DeployStatus status={d.status} />
                  <span className="rl-name">#{d.id} {d.project_name}{d.commit ? <span className="muted mono"> · {d.commit.slice(0, 7)}</span> : null}</span>
                  <span className="muted xsmall nowrap">{timeAgo(d.finished_at || d.created_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
