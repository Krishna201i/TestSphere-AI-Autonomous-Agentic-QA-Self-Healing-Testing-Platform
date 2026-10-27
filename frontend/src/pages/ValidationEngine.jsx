import React, { useState } from 'react';
import { useWorkspace } from '../state/Workspace';
import { executionStats, pct, retestStats, timeAgo } from '../lib/derive';
import { HealthBox, ResultTiles } from '../components/ValidationCard';
import Deployments from '../components/Deployments';

export default function ValidationEngine({ onNavigate }) {
  const { executions, executionTotals, testCases, findings, retests, retest, retesting } = useWorkspace();
  const ex = executionStats(executions, executionTotals);
  const rt = retestStats(retests);
  const nameOf = (id) => testCases.find((t) => t.id === id)?.name || `Test case #${id}`;
  // Approved fixes are listed before their first retest, so they can get one
  const approvedOrTested = findings.filter((f) => f.approved_by || retests[f.key]);
  const [retestErrors, setRetestErrors] = useState({});

  function onRetest(f) {
    setRetestErrors((prev) => ({ ...prev, [f.key]: null }));
    retest(f).catch((err) => setRetestErrors((prev) => ({ ...prev, [f.key]: err.message })));
  }

  return (
    <div className="page">
      <div className="page-title">
        <div>
          <h1>Validation Engine</h1>
          <p>Every fix is checked by re-running what found it: functional tests for QA failures, the original security check for findings.</p>
        </div>
      </div>

      <div className="grid-main-side">
        <section className="card">
          <div className="card-head"><h3>Validation runs</h3></div>
          <ResultTiles />
          <dl className="kv">
            <dt>Executions</dt><dd>{ex.total} finished · {ex.passed} passed · {ex.healed} healed · {ex.failed} failed</dd>
            <dt>Pass rate</dt><dd>{pct(ex.passRate)} (healed runs count as passing)</dd>
            <dt>Security retests</dt><dd>{rt.total} run · {rt.pass} verified fixed ({pct(rt.rate)})</dd>
          </dl>
        </section>
        <div className="stack-lg">
          <Deployments onNavigate={onNavigate} />
          <section className="card">
            <div className="card-head"><h3>TestSphere API health</h3></div>
            <HealthBox />
          </section>
        </div>
      </div>

      <section className="card">
        <div className="card-head"><h3>Security retests</h3><span className="muted small">{rt.total}</span></div>
        {approvedOrTested.length === 0 ? (
          <div className="empty">
            <span className="empty-title">No approved fixes yet</span>
            Approve a fix in Remediation, apply it on your app, then retest it here.
            <button type="button" className="btn btn-sm" onClick={() => onNavigate('remediation')}>Open Remediation</button>
          </div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Finding</th><th>Result</th><th>When</th><th /></tr></thead>
              <tbody>
                {approvedOrTested.map((f) => (
                  <tr key={f.key}>
                    <td className="cell-wrap">{f.title}<div className="mono small muted">{f.check_id} · {f.component}</div></td>
                    <td>
                      {retests[f.key]
                        ? <span className={`status ${retests[f.key].result}`}>{retests[f.key].result}</span>
                        : <span className="muted small">not retested yet</span>}
                    </td>
                    <td className="small muted">{retests[f.key] ? timeAgo(retests[f.key].at) : `approved ${timeAgo(f.approved_at)}`}</td>
                    <td className="text-right">
                      <button type="button" className="btn btn-sm" disabled={retesting === f.key} onClick={() => onRetest(f)}>
                        {retesting === f.key ? 'Retesting…' : 'Retest'}
                      </button>
                      {retestErrors[f.key] && <div className="bad-text small cell-wrap" role="alert">{retestErrors[f.key]}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <div className="card-head"><h3>Test executions</h3><span className="muted small">{executions.length > 50 ? `latest 50 of ${ex.total} finished` : executions.length}</span></div>
        {executions.length === 0 ? <div className="empty">No executions yet.</div> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>#</th><th>Test case</th><th>Status</th><th>Duration</th><th>Detail</th><th>When</th></tr></thead>
              <tbody>
                {[...executions].reverse().slice(0, 50).map((e) => (
                  <tr key={e.id}>
                    <td>{e.id}</td>
                    <td className="cell-wrap">{nameOf(e.test_case_id)}</td>
                    <td><span className={`status ${e.status}`}>{e.status}</span></td>
                    <td className="small">{e.duration_ms != null ? `${(e.duration_ms / 1000).toFixed(1)}s` : '—'}</td>
                    <td className="mono small cell-wrap">{e.error_message || ''}</td>
                    <td className="small muted">{timeAgo(e.completed_at || e.created_at)}</td>
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
