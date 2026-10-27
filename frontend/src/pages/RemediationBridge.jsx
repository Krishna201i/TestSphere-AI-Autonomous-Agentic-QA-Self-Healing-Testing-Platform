import React, { useState } from 'react';
import { useWorkspace } from '../state/Workspace';
import { ApprovalControls, DiffView } from '../components/RemediationCard';
import FixPatchCard from '../components/FixPatch';
import { timeAgo } from '../lib/derive';
import { selectableRow } from '../lib/a11y';

function proposalState(f, approvals, retests) {
  if (retests[f.key]?.result === 'pass') return ['resolved', 'Resolved'];
  if (approvals[f.key]) return ['HEALED', 'Approved'];
  if (f.remediation?.kind === 'manual') return ['PENDING', 'Manual'];
  return ['open', 'Awaiting approval'];
}

function Snippets({ snippets }) {
  const names = Object.keys(snippets || {});
  const [tab, setTab] = useState(names[0]);
  if (!names.length) return null;
  const current = snippets[tab] ? tab : names[0];
  return (
    <div className="subbox stack">
      <div className="approve-row">
        <span className="title">Apply on the target</span>
        <div className="tabs">
          {names.map((n) => (
            <button key={n} type="button" className={`tab ${n === current ? 'active' : ''}`} onClick={() => setTab(n)}>{n}</button>
          ))}
        </div>
      </div>
      <pre className="code" tabIndex={0} aria-label={`${current} configuration`}>{snippets[current]}</pre>
    </div>
  );
}

function LocatorHealing() {
  const { lastRun, executions } = useWorkspace();
  const healedSteps = (lastRun?.engine_steps || []).filter((s) => s.healing);
  const healedRuns = executions.filter((e) => e.status === 'HEALED').slice(-8).reverse();

  return (
    <section className="card">
      <div className="card-head">
        <h3>Locator Self-Healing</h3>
        <span className="muted small">fallback locators first, then a fingerprint scan</span>
      </div>
      {healedSteps.length === 0 && healedRuns.length === 0 && (
        <div className="empty">No healing activity yet. Heals appear when a test's locator breaks and the engine repairs it.</div>
      )}
      {healedSteps.map((s) => (
        <div key={s.step_id} className="subbox">
          <div className="approve-row">
            <span className="title">{lastRun.label} · step {s.step_id}</span>
            <span className={`status ${s.status === 'healed' ? 'HEALED' : 'FAILED'}`}>{s.status}</span>
          </div>
          <dl className="kv mt-2">
            <dt>Original</dt><dd className="mono small">{s.healing.original_locator}</dd>
            <dt>Healed to</dt><dd className="mono small">{s.healing.selected_locator || '— refused (no safe candidate)'}</dd>
            <dt>Strategy</dt><dd>{s.healing.strategy_used} · confidence {Math.round(s.healing.confidence * 100)}%</dd>
          </dl>
          {s.healing.candidates.length > 0 && (
            <div className="table-wrap mt-2">
              <table className="table">
                <thead><tr><th>Candidate</th><th>Score</th><th>Attr</th><th>Text</th><th>Pos</th><th>Struct</th></tr></thead>
                <tbody>
                  {s.healing.candidates.slice(0, 5).map((c) => (
                    <tr key={c.locator}>
                      <td className="mono small cell-wrap">{c.locator}</td>
                      <td>{c.score.toFixed(2)}</td>
                      {['attribute', 'text', 'position', 'structure'].map((k) => <td key={k} className="small">{c.signals[k].toFixed(2)}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ))}
      {healedRuns.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Execution</th><th>Healed</th><th>When</th></tr></thead>
            <tbody>
              {healedRuns.map((e) => (
                <tr key={e.id}><td>#{e.id}</td><td className="mono small cell-wrap">{e.error_message}</td><td className="small muted">{timeAgo(e.completed_at)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default function RemediationBridge({ onNavigate }) {
  const { lastScan, selectedKey, setSelectedKey, approvals, retests } = useWorkspace();
  const findings = lastScan?.findings || [];
  const selected = findings.find((f) => f.key === selectedKey) || findings.find((f) => f.remediation?.kind === 'header') || findings[0];

  return (
    <div className="page">
      <div className="page-title">
        <div>
          <h1>Self-Healing Remediation Bridge</h1>
          <p>Fix proposals built from what the target actually returned. Nothing is changed without a human approval, and nothing counts as fixed until the original check passes a retest.</p>
        </div>
      </div>

      {!lastScan ? (
        <section className="card">
          <div className="empty">
            <span className="empty-title">No findings to fix yet</span>
            Fix proposals appear after a security scan.
            <button type="button" className="btn btn-sm" onClick={() => onNavigate('attacker')}>Run a scan</button>
          </div>
        </section>
      ) : (
        <div className="grid-side-main">
          <section className="card">
            <div className="card-head"><h3>Proposals</h3><span className="muted small">{findings.length}</span></div>
            <div className="table-wrap">
              <table className="table">
                <tbody>
                  {findings.map((f) => {
                    const [cls, label] = proposalState(f, approvals, retests);
                    return (
                      <tr key={f.key} className={`selectable ${selected?.key === f.key ? 'selected' : ''}`} {...selectableRow(() => setSelectedKey(f.key), selected?.key === f.key)}>
                        <td><span className={`sev ${f.severity}`}>{f.severity}</span></td>
                        <td className="cell-wrap">{f.title}<div className="mono small muted">{f.check_id}</div></td>
                        <td><span className={`status ${cls}`}>{label}</span></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          {selected && (
            <section className="card">
              <div className="card-head">
                <h3>{selected.title}</h3>
                <span className={`sev ${selected.severity}`}>{selected.severity}</span>
              </div>
              {selected.remediation?.kind === 'header' ? (
                <>
                  <div className="subbox flush">
                    <div className="approval-head">Human-in-the-Loop approval required for {selected.check_id}</div>
                    <DiffView diff={selected.remediation.diff} />
                  </div>
                  <Snippets snippets={selected.remediation.snippets} />
                  <ApprovalControls finding={selected} />
                </>
              ) : (
                <div className="subbox">
                  <h4>Manual change required</h4>
                  <p className="m-0">{selected.remediation?.summary || selected.recommendation}</p>
                  <p className="hint">This needs a change in your code or infrastructure. Header, CORS and cookie fixes can be made for you as a patch or pull request in <b>Fix patch for your code</b> below; make anything else by hand. Retest after the change:</p>
                  <ApprovalControls finding={selected} />
                </div>
              )}
            </section>
          )}
        </div>
      )}

      {lastScan && <FixPatchCard targetUrl={lastScan.url} />}

      <LocatorHealing />
    </div>
  );
}
