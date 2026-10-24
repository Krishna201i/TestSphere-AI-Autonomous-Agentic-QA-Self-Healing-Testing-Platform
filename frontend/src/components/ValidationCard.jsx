import React from 'react';
import { Activity, Rocket } from 'lucide-react';
import { useWorkspace } from '../state/Workspace';
import { AnimatedNumber, Sparkline } from './charts';
import { deployState, executionStats, healthStats, retestStats, timeAgo } from '../lib/derive';

const asPct = (v) => `${Math.round(v * 100)}%`;

function ResultTile({ label, rate, detail, empty, tone }) {
  return (
    <div className="result-tile">
      <span className="rt-label">{label}</span>
      <span className={`rt-value ${rate == null ? 'none' : ''}`}><AnimatedNumber value={rate == null ? null : rate * 100} format={(v) => `${Math.round(v)}%`} /></span>
      <div className={`meter ${tone}`} aria-hidden="true"><span style={{ width: rate == null ? 0 : asPct(rate) }} /></div>
      <span className="rt-detail">{rate == null ? empty : detail}</span>
    </div>
  );
}

/** Pass rate, self-heal rate and verified fixes as three equal tiles. */
export function ResultTiles() {
  const { executions, executionTotals, retests } = useWorkspace();
  const ex = executionStats(executions, executionTotals);
  const rt = retestStats(retests);
  const broken = ex.healed + ex.failed;
  return (
    <div className="result-tiles">
      <ResultTile label="Tests passed" rate={ex.passRate} tone="good"
        detail={`${ex.passed + ex.healed} of ${ex.total} tests`} empty="No test runs yet" />
      <ResultTile label="Self-healed" rate={ex.healRate}
        detail={`${ex.healed} of ${broken} broken tests repaired`} empty="Nothing has broken yet" />
      <ResultTile label="Fixes verified" rate={rt.rate} tone="good"
        detail={`${rt.pass} of ${rt.total} security retests passed`} empty="No retests yet" />
    </div>
  );
}

/** The platform's own API health: state, latency, uptime and a sparkline. */
export function HealthBox() {
  const { health } = useWorkspace();
  const h = healthStats(health);
  const state = !h.online ? ['bad-text', 'Unreachable'] : h.dbDown ? ['warn-text', 'Database down'] : ['ok-text', 'Operational'];
  return (
    <div className="subbox tinted stack-sm">
      <div className="health-row">
        <span className="row"><Activity size={16} aria-hidden="true" /> API <span className={state[0]}>{state[1]}</span></span>
        <span>Latency <b>{h.latency == null ? '—' : `${h.latency} ms`}</b> · Uptime <b>{h.successRate == null ? '—' : asPct(h.successRate)}</b></span>
      </div>
      <Sparkline samples={health} />
      <span className="xsmall muted">{health.length === 1 ? 'First check' : `Last ${health.length} checks`}, every 3 seconds</span>
    </div>
  );
}

/** The newest pipeline runs, one line each. */
export function LatestRuns({ onNavigate, limit = 4 }) {
  const { pipelineRuns } = useWorkspace();
  const runs = (pipelineRuns || []).slice(0, limit);
  return (
    <div className="stack-sm">
      <div className="row-between">
        <h4 className="section-title m-0">Latest runs</h4>
        {runs.length > 0 && <button type="button" className="link-btn small" onClick={() => onNavigate('autopilot')}>All runs</button>}
      </div>
      {runs.length === 0 ? (
        <div className="empty">
          <span className="empty-title">No pipeline runs yet</span>
          <button type="button" className="btn btn-sm" onClick={() => onNavigate('autopilot')}>Run the pipeline</button>
        </div>
      ) : (
        <ul className="run-list">
          {runs.map((r) => (
            <li key={r.id}>
              <button type="button" className="run-link" onClick={() => onNavigate('runs', { tab: String(r.id) })}>
                <span className={`status run-${r.status}`}>{r.status}</span>
                <span className="rl-name">#{r.id} {r.project_name}{r.summary ? <span className="muted"> · {r.summary.passed}/{r.summary.total} passed</span> : null}</span>
                <span className="muted xsmall nowrap">{timeAgo(r.finished_at || r.started_at || r.created_at)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function DeployFoot({ onNavigate }) {
  const { deployments, projects } = useWorkspace();
  const { state, note } = deployState(deployments, projects);
  return (
    <div className="card-foot">
      <span className={`row small ${state === 'done' ? 'ok-text' : state === 'failed' ? 'bad-text' : 'muted'}`}>
        <Rocket size={14} aria-hidden="true" /> Deploy: {note}
      </span>
      <button type="button" className="link-btn small" onClick={() => onNavigate('validation')}>Deployments</button>
    </div>
  );
}

export default function ValidationCard({ onNavigate }) {
  return (
    <section className="card" aria-labelledby="validation-title">
      <div className="card-head">
        <h3 id="validation-title">Results</h3>
      </div>
      <ResultTiles />
      <LatestRuns onNavigate={onNavigate} />
      <HealthBox />
      <DeployFoot onNavigate={onNavigate} />
    </section>
  );
}
