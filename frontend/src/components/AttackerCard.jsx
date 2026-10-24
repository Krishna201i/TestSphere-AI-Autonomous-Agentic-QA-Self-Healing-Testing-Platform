import React from 'react';
import { AlertTriangle, ShieldCheck } from 'lucide-react';
import { useWorkspace } from '../state/Workspace';
import { RadarChart } from './charts';
import { RADAR_AXES, SEVERITY_ORDER, pathOf, radarValues, timeAgo, topFinding } from '../lib/derive';

export default function AttackerCard({ onOpen }) {
  const { lastScan, scanning } = useWorkspace();
  const findings = lastScan?.findings || [];
  const top = topFinding(findings);
  const counts = SEVERITY_ORDER.map((s) => [s, findings.filter((f) => f.severity === s).length]).filter(([, n]) => n);

  return (
    <section className="card" aria-labelledby="attacker-title">
      <div className="card-head">
        <h3 id="attacker-title">Security scan</h3>
        <span className="pill blue" title="Passive checks only, and only hosts on the server's scope allowlist"><ShieldCheck size={12} /> Safe mode</span>
      </div>
      {lastScan && <p className="card-sub cell-wrap">{pathOf(lastScan.final_url || lastScan.url)} · {timeAgo(lastScan.at)}</p>}

      {scanning && <div className="empty">Scanning the target: one GET per page, scope-checked.</div>}
      {!scanning && !lastScan && (
        <div className="empty">
          <span className="empty-title">No scan yet</span>
          Checks headers, cookies, CORS, TLS and forms without sending payloads.
          <button type="button" className="btn btn-sm" onClick={onOpen}>Run a passive scan</button>
        </div>
      )}
      {!scanning && lastScan && (
        <>
          {counts.length > 0 && (
            <div className="pill-row">{counts.map(([s, n]) => <span key={s} className={`sev ${s}`}>{n} {s}</span>)}</div>
          )}
          {top ? (
            <div className="finding-lead">
              <span className="fl-title"><AlertTriangle size={16} aria-hidden="true" /> {top.title}</span>
              <span className="fl-body">{top.root_cause}</span>
            </div>
          ) : (
            <div className="finding-lead ok"><span className="fl-title"><ShieldCheck size={16} aria-hidden="true" /> No weaknesses found by passive checks</span></div>
          )}
          <div className="radar-wrap">
            <RadarChart values={radarValues(findings)} labels={RADAR_AXES.map((a) => a.label)} size={240} />
          </div>
        </>
      )}

      <div className="card-foot">
        <span className="small muted">{findings.length} finding{findings.length === 1 ? '' : 's'} · passive mode</span>
        <button type="button" className="btn btn-sm" onClick={onOpen}>Open findings</button>
      </div>
    </section>
  );
}
