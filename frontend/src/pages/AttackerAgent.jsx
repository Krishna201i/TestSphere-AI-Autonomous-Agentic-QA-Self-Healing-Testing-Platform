import React, { useState } from 'react';
import { ShieldCheck } from 'lucide-react';
import { useWorkspace } from '../state/Workspace';
import { RadarChart } from '../components/charts';
import { RADAR_AXES, SEVERITY_ORDER, radarValues, timeAgo, urlError } from '../lib/derive';
import { selectableRow } from '../lib/a11y';

export default function AttackerAgent({ onNavigate }) {
  const ws = useWorkspace();
  const { lastScan, scanning, runScan, selectedKey, setSelectedKey, retests } = ws;
  const [url, setUrl] = useState('');
  const [error, setError] = useState(null);

  const findings = lastScan?.findings || [];
  const selected = findings.find((f) => f.key === selectedKey) || findings[0] || null;

  async function onScan(e) {
    e.preventDefault();
    setError(null);
    const target = url.trim() || lastScan?.url || '';  // empty field = rescan the last target
    const bad = urlError(target);
    if (bad) {
      setError(bad);
      return;
    }
    try {
      await runScan(target);
    } catch (err) {
      setError(err.status === 403
        ? `${err.message}. Add the host to SECURITY_SCAN_ALLOWED_HOSTS on the backend if you own it.`
        : err.message);
    }
  }

  return (
    <div className="page">
      <div className="page-title">
        <div>
          <h1>AI Attacker Agent</h1>
          <p>Authorized, passive security testing: one GET per page, no payloads, every request and redirect checked against the server's scope allowlist.</p>
        </div>
        <span className="pill blue"><ShieldCheck size={12} /> Safe mode</span>
      </div>

      <section className="card">
        <form className="form-row" onSubmit={onScan}>
          <label className="field wide">
            Target URL
            <input className="input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder={lastScan?.url || 'http://127.0.0.1:8000/'} />
          </label>
          <button className="btn btn-primary" type="submit" disabled={scanning}>{scanning ? 'Scanning…' : 'Run passive scan'}</button>
        </form>
        {ws.applications.length > 0 && (
          <div className="row small">
            <span className="muted">Saved targets:</span>
            {ws.applications.slice(0, 6).map((a) => (
              <button key={a.id} type="button" className="chip" onClick={() => setUrl(a.base_url)}>{a.name}</button>
            ))}
          </div>
        )}
        {error && <div className="error-text">{error}</div>}
        <div className="hint">
          In scope on this backend: <b>{ws.system?.scan_scope ? ws.system.scan_scope.join(', ') : 'unknown (backend offline or outdated)'}</b>.
          To scan a site you own or are authorized to test, add its host to <code>SECURITY_SCAN_ALLOWED_HOSTS</code> on the backend and restart it.
        </div>
      </section>

      <div className="grid-main-side">
        <section className="card">
          <div className="card-head">
            <h3>Findings</h3>
            {lastScan && <span className="muted small">{lastScan.final_url}{lastScan.status_code ? ` · HTTP ${lastScan.status_code}` : ''} · {timeAgo(lastScan.at)}</span>}
          </div>
          {!lastScan && <div className="empty">Run a scan to see findings.</div>}
          {lastScan && findings.length === 0 && <div className="empty">No weaknesses found by passive checks.</div>}
          {findings.length > 0 && (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Severity</th><th>Check</th><th>Finding</th><th>Retest</th></tr></thead>
                <tbody>
                  {findings.map((f) => (
                    <tr key={f.key} className={`selectable ${selected?.key === f.key ? 'selected' : ''}`} {...selectableRow(() => setSelectedKey(f.key), selected?.key === f.key)}>
                      <td><span className={`sev ${f.severity}`}>{f.severity}</span></td>
                      <td className="mono small">{f.check_id}</td>
                      <td className="cell-wrap">{f.title}</td>
                      <td>{retests[f.key] ? <span className={`status ${retests[f.key].result}`}>{retests[f.key].result}</span> : <span className="muted small">—</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="card">
          <div className="card-head"><h3>Exposure Radar</h3></div>
          <div className="radar-wrap">
            <RadarChart values={radarValues(findings)} labels={RADAR_AXES.map((a) => a.label)} size={260} />
          </div>
          <div className="pill-row center">
            {SEVERITY_ORDER.map((s) => (
              <span key={s} className={`sev ${s}`}>{s}: {findings.filter((f) => f.severity === s).length}</span>
            ))}
          </div>
        </section>
      </div>

      {selected && (
        <section className="card">
          <div className="card-head">
            <h3>{selected.title}</h3>
            <span className={`sev ${selected.severity}`}>{selected.severity}</span>
          </div>
          <dl className="kv">
            <dt>Check</dt><dd className="mono">{selected.check_id}</dd>
            <dt>Component</dt><dd>{selected.component}</dd>
            <dt>Evidence</dt><dd>{selected.evidence.map((e, i) => <div key={i} className="mono small">{e}</div>)}</dd>
            <dt>Root cause</dt><dd>{selected.root_cause}</dd>
            <dt>Recommendation</dt><dd>{selected.recommendation}</dd>
            <dt>Confidence</dt><dd>{Math.round(selected.confidence * 100)}%</dd>
          </dl>
          <div className="row">
            <button type="button" className="btn btn-primary" onClick={() => { setSelectedKey(selected.key); onNavigate('remediation'); }}>
              Open fix proposal
            </button>
          </div>
        </section>
      )}

      {lastScan?.response_headers?.length > 0 && (
        <section className="card">
          <div className="card-head"><h3>Observed response headers</h3><span className="muted small">sensitive values redacted</span></div>
          <div className="table-wrap">
            <table className="table">
              <tbody>
                {lastScan.response_headers.map(([k, v], i) => (
                  <tr key={i}><td className="mono small nowrap">{k}</td><td className="mono small cell-wrap">{v}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
