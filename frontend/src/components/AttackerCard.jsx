import React from 'react';
import { AlertTriangle } from 'lucide-react';
import { useWorkspace } from '../state/Workspace';
import { Bars, RadarChart } from './charts';
import { RADAR_AXES, pathOf, radarValues, timeAgo, topFinding } from '../lib/derive';

export default function AttackerCard({ onOpen }) {
  const { lastScan, scanHistory, scanning } = useWorkspace();
  const findings = lastScan?.findings || [];
  const top = topFinding(findings);

  return (
    <section className="card" aria-labelledby="attacker-title">
      <div className="card-head">
        <h3 id="attacker-title">AI Attacker Agent (Red Team)</h3>
        <span className="card-chip">Card</span>
      </div>

      <div className="attacker-body">
        <div className="radar-col">
          <span className="label">Radar Map Visualizer</span>
          <RadarChart values={radarValues(findings)} labels={RADAR_AXES.map((a) => a.label)} size={230} />
          <span className="pill blue" title="Passive checks only, and only hosts on the server's scope allowlist">
            Safe-Mode: <span style={{ color: 'var(--pill-blue-fg)' }}>Enforced</span>
          </span>
        </div>

        <div className="evidence-col">
          <div className="subbox">
            <h4>Live Scan Evidence</h4>
            {scanning && <div className="evidence-lines">Scanning target… one GET per page, scope-checked.</div>}
            {!scanning && !lastScan && (
              <div className="evidence-lines muted">
                No scan yet.{' '}
                <button type="button" className="btn btn-sm" onClick={onOpen}>Run a passive scan</button>
              </div>
            )}
            {!scanning && lastScan && (
              <div className="evidence-lines">
                <div>Discovered target: {pathOf(lastScan.final_url || lastScan.url)}</div>
                <div>Checks run: headers, cookies, CORS, TLS, forms ({timeAgo(lastScan.at)})</div>
                {top ? (
                  <>
                    <div>Finding: <span className="warn"><AlertTriangle size={14} style={{ verticalAlign: '-2px' }} /> {top.title}</span></div>
                    <div>Severity: {cap(top.severity)} / Impact: {top.root_cause}</div>
                  </>
                ) : (
                  <div style={{ color: 'var(--green-text)' }}>No weaknesses found by passive checks.</div>
                )}
              </div>
            )}
          </div>

          <div className="subbox bars-box">
            <Bars values={scanHistory.map((s) => s.count)} />
            <div className="rate">Exploit Success Rate: 0.0%</div>
            <div className="small muted">Passive mode · no payloads sent · {findings.length} finding(s) in last scan</div>
          </div>
        </div>
      </div>
    </section>
  );
}

const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
