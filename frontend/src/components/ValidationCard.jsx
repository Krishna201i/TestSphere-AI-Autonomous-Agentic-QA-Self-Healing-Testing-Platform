import React from 'react';
import { CheckCircle2 } from 'lucide-react';
import { useWorkspace } from '../state/Workspace';
import { Ring, Waveform } from './charts';
import { executionStats, healthStats, pct, retestStats } from '../lib/derive';

export function HealthWaveformBox() {
  const { health } = useWorkspace();
  const h = healthStats(health);
  return (
    <div className="subbox">
      <div className="wave-head">
        <h4>{!h.online ? 'Backend Unreachable' : h.dbDown ? 'Degraded (database down)' : '200 OK'} Health Waveform</h4>
        <span className="meta">
          Response Time: <b>{h.latency == null ? '—' : `${h.latency}ms`}</b>{'  '}
          Success Rate: <b>{pct(h.successRate)}</b>
        </span>
      </div>
      <Waveform samples={health} />
    </div>
  );
}

export function ValidationRings() {
  const { executions, executionTotals, retests } = useWorkspace();
  const ex = executionStats(executions, executionTotals);
  const rt = retestStats(retests);
  return (
    <div className="rings">
      <div className="ring-item">
        <Ring value={ex.passRate} color="var(--blue)" />
        <span>Functional Tests</span>
        <span className="sub">[{ex.passed + ex.healed}/{ex.total} passed]</span>
      </div>
      <div className="ring-item">
        <Ring value={ex.healRate} color="var(--green)" />
        <span>Self-Heals</span>
        <span className="sub">[{ex.healed}/{ex.healed + ex.failed} broken]</span>
      </div>
      <div className="ring-item">
        <Ring value={rt.rate} color="var(--green)" />
        <span>Security Retest</span>
        <span className="sub">[{rt.pass}/{rt.total} fixed]</span>
      </div>
    </div>
  );
}

export default function ValidationCard() {
  const { executions, executionTotals } = useWorkspace();
  const ex = executionStats(executions, executionTotals);

  return (
    <section className="card" aria-labelledby="validation-title">
      <div className="card-head">
        <h3 id="validation-title">Automated Validation &amp; Deployment Pulse</h3>
        <span className="card-chip">Card</span>
      </div>

      <div className="validation-top">
        <div className="subbox">
          <h4>Validation Runs</h4>
          <ValidationRings />
        </div>
        <div className="suite-side">
          <div className="subbox">
            <h4 style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              Test Suite
              {ex.total > 0 && ex.failed === 0 && <><CheckCircle2 size={18} color="var(--green)" /><CheckCircle2 size={18} color="var(--green)" /></>}
            </h4>
            {ex.total ? (
              <div className="big-stat">{pct(ex.passRate, 0)} <span>Passed</span></div>
            ) : (
              <div className="muted">No executions yet</div>
            )}
          </div>
          <div className="subbox shield" title="Deployment and rollback for target apps are not built yet (module 5.7)">
            <span>Rollback Shield: <span className="planned">Planned</span></span>
            <span className="toggle" role="switch" aria-checked="false" aria-disabled="true" />
          </div>
        </div>
      </div>

      <HealthWaveformBox />
    </section>
  );
}
