import React, { useState } from 'react';
import { ShieldCheck } from 'lucide-react';
import { useWorkspace } from '../state/Workspace';
import { RadarChart } from '../components/charts';
import { RADAR_AXES, SEVERITY_ORDER, byTier, confidenceLabel, radarValues, tierCounts, timeAgo, urlError } from '../lib/derive';
import FindingEvidence, { TierPill } from '../components/FindingEvidence';
import ActiveTargets from '../components/ActiveTargets';
import { selectableRow } from '../lib/a11y';
import Pager from '../components/Pager';
import { usePaged } from '../lib/usePaged';

export default function AttackerAgent({ onNavigate }) {
  const ws = useWorkspace();
  const { lastScan, scanning, runScan, selectedKey, setSelectedKey, retests } = ws;
  const [url, setUrl] = useState('');
  const [active, setActive] = useState(false);
  const [error, setError] = useState(null);
  const activeAvailable = Boolean(ws.system?.active_scan);

  // Proven first: the order a reader should act in
  const findings = byTier(lastScan?.findings);
  const tiers = tierCounts(findings);
  const selected = findings.find((f) => f.key === selectedKey) || findings[0] || null;
  const findingPage = usePaged(findings, 10);

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
      await runScan(target, active && activeAvailable);
    } catch (err) {
      setError(err.status === 403 && active
        ? `${err.message} Add and verify the site under Sites for active testing.`
        : err.message);
    }
  }

  return (
    <div className="page">
      <div className="page-title">
        <div>
          <h1>AI Attacker Agent</h1>
          <p>Authorized security testing, scoped to the server's allowlist. Passive by default (one GET per page, no payloads);
            active scanning, where the server allows it, sends test attacks to apps you own.</p>
        </div>
        <span className={`pill ${active && activeAvailable ? 'orange' : 'blue'}`}>
          <ShieldCheck size={12} /> {active && activeAvailable ? 'Active mode' : 'Safe mode'}
        </span>
      </div>

      <section className="card">
        <form className="form-row" onSubmit={onScan}>
          <label className="field wide">
            Target URL
            <input className="input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder={lastScan?.url || 'http://127.0.0.1:8000/'} />
          </label>
          <button className="btn btn-primary" type="submit" disabled={scanning}>
            {scanning ? 'Scanning…' : (active && activeAvailable ? 'Run active scan' : 'Run passive scan')}
          </button>
        </form>
        {activeAvailable && (
          <label className="check">
            <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
            Active scan: also send test attacks (reflected XSS, SQL injection, open redirect). Only for apps you own.
          </label>
        )}
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
          {ws.system?.passive_any_host
            ? <>Passive scans work on <b>any public website</b> (one normal page request, no attacks). Active scans run only on sites
              you own: add and verify them under <b>Sites for active testing</b> below.</>
            : <>In scope on this backend: <b>{ws.system?.scan_scope ? ws.system.scan_scope.join(', ') : 'unknown (backend offline or outdated)'}</b>.
              To scan another site you own, add it under <b>Sites for active testing</b> below.</>}
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
            <p className="small">
              <b>{tiers.proven} proven</b>
              {tiers.unconfirmed > 0 && <> · {tiers.unconfirmed} to check by hand</>}
              {tiers.hardening > 0 && <> · <span className="muted">{tiers.hardening} hardening suggestion{tiers.hardening === 1 ? '' : 's'} (missing defences, not counted as vulnerabilities)</span></>}
            </p>
          )}
          {findings.length > 0 && (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Proof</th><th>Severity</th><th>Finding</th><th>Retest</th></tr></thead>
                <tbody>
                  {findingPage.items.map((f) => (
                    <tr key={f.key} className={`selectable ${selected?.key === f.key ? 'selected' : ''}`} {...selectableRow(() => setSelectedKey(f.key), selected?.key === f.key)}>
                      <td><TierPill finding={f} /></td>
                      <td><span className={`sev ${f.severity}`}>{f.severity}</span></td>
                      <td className="cell-wrap">{f.title}<div className="mono small muted">{f.check_id}</div></td>
                      <td>{retests[f.key] ? <span className={`status ${retests[f.key].result}`}>{retests[f.key].result}</span> : <span className="muted small">—</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <Pager paged={findingPage} label="findings" />
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
            <span className="row"><TierPill finding={selected} /> <span className={`sev ${selected.severity}`}>{selected.severity}</span></span>
          </div>
          {selected.ai && (
            <div className="ai-note">
              <div className="ai-note-head"><span className="pill blue">AI triage</span>{selected.ai.summary}</div>
              {selected.ai.explanation && <p className="muted small">{selected.ai.explanation}</p>}
              {selected.ai.remediation && <p><b>Suggested fix:</b> {selected.ai.remediation}</p>}
            </div>
          )}
          <dl className="kv">
            <dt>Check</dt><dd className="mono">{selected.check_id}</dd>
            <dt>Component</dt><dd>{selected.component}</dd>
            <dt>Evidence</dt><dd>{selected.evidence.map((e, i) => <div key={i} className="mono small">{e}</div>)}</dd>
            <dt>Root cause</dt><dd>{selected.root_cause}</dd>
            <dt>Recommendation</dt><dd>{selected.recommendation}</dd>
            <dt>Confidence</dt>
            <dd>
              {Math.round(selected.confidence * 100)}%
              {confidenceLabel(selected) && (
                <span className={`pill ${confidenceLabel(selected).tone} ml-2`}>{confidenceLabel(selected).text}</span>
              )}
            </dd>
          </dl>
          <FindingEvidence finding={selected} />
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

      <ActiveTargets onPick={(site) => {
        setUrl(`${site}/`);
        if (activeAvailable) setActive(true);
        window.scrollTo({ top: 0, behavior: 'smooth' });
      }} />
    </div>
  );
}
