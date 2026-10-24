import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Download, FileJson, Printer, Search } from 'lucide-react';
import { useWorkspace } from '../state/Workspace';
import { getPipelineRuns } from '../services/api';
import { SEVERITY_ORDER, timeAgo, toDate } from '../lib/derive';
import { RunStatus } from './Autopilot';

const PERIODS = [['7', 'Last 7 days'], ['30', 'Last 30 days'], ['all', 'All time']];
const FINISHED = ['passed', 'failed'];
// Result colors (validated: lightness band, CVD separation; legend + table carry identity too)
const RESULT_SERIES = [
  { key: 'passed', label: 'Passed' },
  { key: 'healed', label: 'Self-healed' },
  { key: 'failed', label: 'Failed' },
];
const PAGE_SIZE = 100;

function useWidth() {
  const ref = useRef(null);
  const [width, setWidth] = useState(640);
  useLayoutEffect(() => {
    if (!ref.current) return undefined;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.max(280, Math.round(entry.contentRect.width))));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

function hostOf(url) {
  try {
    return new URL(url).host.toLowerCase();
  } catch {
    return '';
  }
}

const pctText = (v) => (v == null ? '—' : `${Math.round(v * 100)}%`);
const runLabel = (r) => `#${r.id}`;

/** Single-series pass-rate line with a crosshair tooltip. */
function PassRateChart({ runs }) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState(null);
  const height = 210;
  const pad = { l: 40, r: 44, t: 14, b: 26 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;
  const pts = runs.map((r, i) => ({
    run: r,
    rate: r.summary.total ? r.summary.passed / r.summary.total : 0,
    x: pad.l + (runs.length === 1 ? w / 2 : (i / (runs.length - 1)) * w),
  })).map((p) => ({ ...p, y: pad.t + (1 - p.rate) * h }));
  const path = pts.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
  const last = pts[pts.length - 1];

  function onMove(e) {
    const box = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - box.left;
    let best = null;
    for (const p of pts) if (!best || Math.abs(p.x - x) < Math.abs(best.x - x)) best = p;
    setHover(best);
  }

  return (
    <div className="chart" ref={ref}>
      <svg width={width} height={height} role="img" aria-label="Pass rate per pipeline run"
        onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        {[0, 0.5, 1].map((t) => {
          const y = pad.t + (1 - t) * h;
          return (
            <g key={t}>
              <line x1={pad.l} x2={width - pad.r} y1={y} y2={y} className="chart-grid" />
              <text x={pad.l - 8} y={y + 4} textAnchor="end" className="chart-tick">{t * 100}%</text>
            </g>
          );
        })}
        {pts.length > 0 && <path d={`${path} L${last.x},${pad.t + h} L${pts[0].x},${pad.t + h} Z`} className="area-pass" />}
        <path d={path} className="line-pass" />
        {hover && <line x1={hover.x} x2={hover.x} y1={pad.t} y2={pad.t + h} className="chart-crosshair" />}
        {(hover ? [hover] : last ? [last] : []).map((p) => (
          <circle key={p.run.id} cx={p.x} cy={p.y} r="5" className="dot-pass" />
        ))}
        {last && !hover && <text x={last.x + 9} y={last.y + 4} className="chart-label">{pctText(last.rate)}</text>}
        {pts.length > 0 && (
          <>
            <text x={pts[0].x} y={height - 6} textAnchor="start" className="chart-tick">{runLabel(pts[0].run)}</text>
            {pts.length > 1 && <text x={last.x} y={height - 6} textAnchor="end" className="chart-tick">{runLabel(last.run)}</text>}
          </>
        )}
      </svg>
      {hover && (
        <div className="chart-tip" style={{ left: Math.min(hover.x + 12, width - 190), top: 8 }}>
          <b>Run {runLabel(hover.run)}</b> · {hover.run.project_name}
          <div>{pctText(hover.rate)} passed ({hover.run.summary.passed}/{hover.run.summary.total})</div>
          <div className="muted">{toDate(hover.run.finished_at).toLocaleString()}</div>
        </div>
      )}
    </div>
  );
}

/** Stacked columns per run: passed / healed / failed, 2px surface gaps, rounded caps. */
function ResultsChart({ runs }) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState(null);
  const height = 210;
  const pad = { l: 34, r: 10, t: 14, b: 26 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;
  const max = Math.max(1, ...runs.map((r) => r.summary.total));
  const step = w / Math.max(runs.length, 1);
  const barW = Math.min(24, Math.max(4, step * 0.6));
  const scale = (n) => (n / max) * h;
  const ticks = [0, Math.ceil(max / 2), max].filter((v, i, a) => a.indexOf(v) === i);

  const columns = runs.map((r, i) => {
    const healed = r.summary.healed || 0;
    const values = { passed: Math.max(0, r.summary.passed - healed), healed, failed: r.summary.failed };
    const x = pad.l + step * i + (step - barW) / 2;
    let y = pad.t + h;
    const segs = [];
    RESULT_SERIES.forEach((s) => {
      const v = values[s.key];
      if (!v) return;
      const sh = scale(v);
      segs.push({ key: s.key, y: y - sh, h: sh });
      y -= sh;
    });
    return { run: r, x, values, segs };
  });

  return (
    <div className="chart" ref={ref}>
      <div className="chart-legend">
        {RESULT_SERIES.map((s) => <span key={s.key}><i className={`swatch series-${s.key}`} />{s.label}</span>)}
      </div>
      <svg width={width} height={height} role="img" aria-label="Test results per pipeline run" onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => {
          const y = pad.t + h - scale(t);
          return (
            <g key={t}>
              <line x1={pad.l} x2={width - pad.r} y1={y} y2={y} className="chart-grid" />
              <text x={pad.l - 8} y={y + 4} textAnchor="end" className="chart-tick">{t}</text>
            </g>
          );
        })}
        {columns.map((c) => (
          <g key={c.run.id} onMouseEnter={() => setHover(c)}>
            <rect x={c.x - (step - barW) / 2} y={pad.t} width={step} height={h} fill="transparent" />
            {c.segs.map((s, idx) => {
              const gap = idx > 0 ? 2 : 0; // surface gap between stacked segments
              const top = idx === c.segs.length - 1;
              const r = top ? Math.min(4, barW / 2, s.h) : 0;
              const y0 = s.y;
              const y1 = s.y + s.h - gap;
              if (y1 - y0 <= 0) return null;
              const d = `M${c.x},${y1} L${c.x},${y0 + r} Q${c.x},${y0} ${c.x + r},${y0} L${c.x + barW - r},${y0} Q${c.x + barW},${y0} ${c.x + barW},${y0 + r} L${c.x + barW},${y1} Z`;
              return <path key={s.key} d={d} className={`series-${s.key}`} opacity={hover && hover.run.id !== c.run.id ? 0.45 : 1} />;
            })}
          </g>
        ))}
        {columns.length > 0 && (
          <>
            <text x={columns[0].x} y={height - 6} className="chart-tick">{runLabel(columns[0].run)}</text>
            {columns.length > 1 && <text x={columns[columns.length - 1].x + barW} y={height - 6} textAnchor="end" className="chart-tick">{runLabel(columns[columns.length - 1].run)}</text>}
          </>
        )}
      </svg>
      {hover && (
        <div className="chart-tip" style={{ left: Math.min(hover.x + barW + 8, width - 190), top: 30 }}>
          <b>Run {runLabel(hover.run)}</b> · {hover.run.project_name}
          {RESULT_SERIES.map((s) => (
            <div key={s.key}><i className={`swatch series-${s.key}`} />{s.label}: {hover.values[s.key]}</div>
          ))}
        </div>
      )}
    </div>
  );
}

function download(name, type, text) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

const csvCell = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;

export default function Reports({ onNavigate }) {
  const { projects, findings } = useWorkspace();
  const [runs, setRuns] = useState(null);
  const [error, setError] = useState(null);
  const [projectId, setProjectId] = useState('all');
  const [period, setPeriod] = useState('30');
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [shown, setShown] = useState(PAGE_SIZE);

  useEffect(() => {
    getPipelineRuns(200).then(setRuns).catch((err) => setError(err.message));
  }, []);

  const project = projects.find((p) => String(p.id) === projectId) || null;

  const data = useMemo(() => {
    const since = period === 'all' ? 0 : Date.now() - Number(period) * 86400000;
    const inScope = (runs || [])
      .filter((r) => !project || r.project_id === project.id)
      .filter((r) => toDate(r.finished_at || r.started_at || r.created_at).getTime() >= since);
    const finished = inScope.filter((r) => FINISHED.includes(r.status) && r.summary).sort((a, b) => a.id - b.id);
    const totals = finished.reduce((t, r) => ({
      total: t.total + r.summary.total, passed: t.passed + r.summary.passed,
      failed: t.failed + r.summary.failed, healed: t.healed + (r.summary.healed || 0),
    }), { total: 0, passed: 0, failed: 0, healed: 0 });
    const regressions = inScope.flatMap((r) => (r.regressions || []).map((g) => ({ ...g, run: r })))
      .sort((a, b) => b.run.id - a.run.id);
    const results = inScope.flatMap((r) => (r.tests || []).map((t) => ({ ...t, run: r })))
      .sort((a, b) => b.run.id - a.run.id || a.execution_id - b.execution_id);
    const host = project ? hostOf(project.app_url) : null;
    const scopedFindings = findings.filter((f) => !host || hostOf(f.target_url) === host);
    return { inScope, finished, totals, regressions, results, scopedFindings };
  }, [runs, project, period, findings]);

  const open = data.scopedFindings.filter((f) => f.status === 'open');
  const bySeverity = SEVERITY_ORDER.map((s) => [s, open.filter((f) => f.severity === s).length]).filter(([, n]) => n);
  const awaitingRetest = open.filter((f) => f.approved_by && f.retest_result !== 'pass').length;
  const resolved = data.scopedFindings.filter((f) => f.status === 'resolved').length;

  const q = query.trim().toLowerCase();
  const results = data.results.filter((t) => {
    const label = t.healed && t.status === 'PASSED' ? 'HEALED' : t.status;
    return (statusFilter === 'all' || label === statusFilter)
      && (!q || `${t.name} ${t.run.project_name} ${t.error || ''}`.toLowerCase().includes(q));
  });

  const perProject = projects
    .filter((p) => !project || p.id === project.id)
    .map((p) => {
      const pr = data.finished.filter((r) => r.project_id === p.id);
      const lastRun = pr[pr.length - 1];
      const t = pr.reduce((a, r) => ({ total: a.total + r.summary.total, passed: a.passed + r.summary.passed }), { total: 0, passed: 0 });
      const host = hostOf(p.app_url);
      return {
        p, runs: pr.length, lastRun,
        rate: t.total ? t.passed / t.total : null,
        regressions: data.regressions.filter((g) => g.run.project_id === p.id).length,
        openFindings: findings.filter((f) => f.status === 'open' && host && hostOf(f.target_url) === host).length,
      };
    });

  const scopeLabel = `${project ? project.name : 'All projects'} · ${PERIODS.find(([v]) => v === period)[1]}`;

  function exportJson() {
    download(`testsphere-report-${new Date().toISOString().slice(0, 10)}.json`, 'application/json', JSON.stringify({
      generated_at: new Date().toISOString(), scope: scopeLabel, totals: data.totals,
      runs: data.inScope, regressions: data.regressions.map(({ run, ...g }) => ({ ...g, run_id: run.id, project: run.project_name })),
      findings: data.scopedFindings,
    }, null, 2));
  }

  function exportCsv() {
    const rows = [['run', 'project', 'trigger', 'finished_at', 'test', 'category', 'result', 'error', 'execution_id']];
    data.results.forEach((t) => rows.push([t.run.id, t.run.project_name, t.run.trigger, t.run.finished_at, t.name, t.category,
      t.healed && t.status === 'PASSED' ? 'HEALED' : t.status, (t.error || '').split('\n')[0], t.execution_id]));
    download(`testsphere-results-${new Date().toISOString().slice(0, 10)}.csv`, 'text/csv', rows.map((r) => r.map(csvCell).join(',')).join('\n'));
  }

  return (
    <div className="page">
      <div className="page-title">
        <div>
          <h1>Reports</h1>
          <p>Every Autopilot result in one place: pass-rate trends, regressions, security posture and each test outcome. <span className="print-only">{scopeLabel} · generated {new Date().toLocaleString()}</span></p>
        </div>
        <div className="page-actions no-print">
          <button type="button" className="btn" onClick={exportCsv} disabled={!data.results.length}><Download size={16} /> CSV</button>
          <button type="button" className="btn" onClick={exportJson} disabled={!data.inScope.length}><FileJson size={16} /> JSON</button>
          <button type="button" className="btn" onClick={() => window.print()}><Printer size={16} /> PDF</button>
        </div>
      </div>

      <div className="form-row center no-print">
        <select className="input select-sm" aria-label="Project" value={projectId} onChange={(e) => { setProjectId(e.target.value); setShown(PAGE_SIZE); }}>
          <option value="all">All projects</option>
          {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <div className="tabs" role="tablist" aria-label="Period">
          {PERIODS.map(([v, l]) => (
            <button key={v} type="button" role="tab" aria-selected={period === v} className={`tab ${period === v ? 'active' : ''}`} onClick={() => setPeriod(v)}>{l}</button>
          ))}
        </div>
      </div>

      {error && <div className="alert-banner inline" role="alert">{error}</div>}
      {runs === null && !error && <div className="empty">Loading results…</div>}

      {runs !== null && (
        <>
          <div className="stat-tiles">
            <div className="stat-tile"><div className="v">{pctText(data.totals.total ? data.totals.passed / data.totals.total : null)}</div><div className="l">Pass rate</div></div>
            <div className="stat-tile"><div className="v">{data.finished.length}</div><div className="l">Completed runs</div></div>
            <div className="stat-tile"><div className="v">{data.totals.total}</div><div className="l">Tests executed</div></div>
            <div className="stat-tile"><div className="v">{data.totals.healed}</div><div className="l">Self-healed</div></div>
            <div className="stat-tile"><div className="v">{data.regressions.length}</div><div className="l">Regressions</div></div>
            <div className="stat-tile"><div className="v">{open.length}</div><div className="l">Open findings</div></div>
          </div>

          {data.finished.length === 0 ? (
            <section className="card">
              <div className="empty">No completed runs in this period. <button type="button" className="link-btn" onClick={() => onNavigate('autopilot')}>Start one in Autopilot</button></div>
            </section>
          ) : (
            <div className="grid-2">
              <section className="card">
                <div className="card-head"><h3>Pass rate per run</h3><span className="muted small">{data.finished.length} runs</span></div>
                <PassRateChart runs={data.finished.slice(-40)} />
              </section>
              <section className="card">
                <div className="card-head"><h3>Results per run</h3><span className="muted small">passed · healed · failed</span></div>
                <ResultsChart runs={data.finished.slice(-40)} />
              </section>
            </div>
          )}

          <div className="grid-2">
            <section className="card">
              <div className="card-head"><h3>Regressions</h3><span className="muted small">{data.regressions.length}</span></div>
              {data.regressions.length === 0 ? <div className="empty">Nothing got worse between runs.</div> : (
                <ul className="timeline">
                  {data.regressions.slice(0, 50).map((g, i) => (
                    <li key={i}>
                      <span className="when">Run #{g.run.id}<br />{timeAgo(g.run.finished_at)}</span>
                      <span className="mark error" />
                      <span className="cell-wrap"><span className="kind">{g.kind} · {g.run.project_name}</span>{g.name}: {g.was} → <b>{g.now}</b>{g.error ? <div className="small muted">{g.error.split('\n')[0]}</div> : null}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="card">
              <div className="card-head"><h3>Security summary</h3><span className="muted small">{open.length} open · {resolved} resolved</span></div>
              {bySeverity.length > 0 ? (
                <div className="pill-row">{bySeverity.map(([s, n]) => <span key={s} className={`sev ${s}`}>{n} {s}</span>)}</div>
              ) : <div className="empty">No open findings{data.scopedFindings.length ? '' : ' — targets in the authorized scan scope are scanned on every run'}.</div>}
              {awaitingRetest > 0 && <div className="hint">{awaitingRetest} approved fix(es) waiting for a passing retest.</div>}
              {open.length > 0 && (
                <div className="table-wrap">
                  <table className="table">
                    <thead><tr><th>Severity</th><th>Finding</th><th>Target</th><th>Seen</th></tr></thead>
                    <tbody>
                      {open.slice(0, 12).map((f) => (
                        <tr key={f.key}>
                          <td><span className={`sev ${f.severity}`}>{f.severity}</span></td>
                          <td className="cell-wrap">{f.title}</td>
                          <td className="mono small cell-wrap">{hostOf(f.target_url) || f.target_url}</td>
                          <td className="small muted">{timeAgo(f.last_seen)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <button type="button" className="btn btn-sm no-print self-start" onClick={() => onNavigate('security')}>Open Security</button>
            </section>
          </div>

          <section className="card">
            <div className="card-head"><h3>Projects</h3><span className="muted small">{perProject.length}</span></div>
            {perProject.length === 0 ? <div className="empty">No projects yet.</div> : (
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>Project</th><th>Runs</th><th>Pass rate</th><th>Last run</th><th>Regressions</th><th>Open findings</th></tr></thead>
                  <tbody>
                    {perProject.map((row) => (
                      <tr key={row.p.id}>
                        <td className="cell-wrap"><b>{row.p.name}</b><div className="small muted mono">{row.p.app_url || '—'}</div></td>
                        <td>{row.runs}</td>
                        <td>{pctText(row.rate)}</td>
                        <td>{row.lastRun ? <><RunStatus status={row.lastRun.status} /> <span className="small muted">#{row.lastRun.id} · {timeAgo(row.lastRun.finished_at)}</span></> : <span className="muted small">no runs</span>}</td>
                        <td>{row.regressions}</td>
                        <td>{row.openFindings}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="card">
            <div className="card-head"><h3>All results</h3><span className="muted small">{results.length} of {data.results.length} test results</span></div>
            <div className="form-row center no-print">
              <div className="search">
                <Search size={18} />
                <input value={query} onChange={(e) => { setQuery(e.target.value); setShown(PAGE_SIZE); }} placeholder="Search tests, projects, errors..." aria-label="Search results" />
              </div>
              <div className="tabs" role="tablist" aria-label="Filter by result">
                {['all', 'PASSED', 'HEALED', 'FAILED'].map((s) => (
                  <button key={s} type="button" role="tab" aria-selected={statusFilter === s} className={`tab ${statusFilter === s ? 'active' : ''}`} onClick={() => { setStatusFilter(s); setShown(PAGE_SIZE); }}>{s === 'all' ? 'all' : s.toLowerCase()}</button>
                ))}
              </div>
            </div>
            {results.length === 0 ? <div className="empty">No test results match.</div> : (
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>Run</th><th>Project</th><th>Test</th><th>Result</th><th>Details</th><th>When</th></tr></thead>
                  <tbody>
                    {results.slice(0, shown).map((t) => (
                      <tr key={`${t.run.id}-${t.execution_id}`}>
                        <td className="small">#{t.run.id}<div className="muted">{t.run.trigger}</div></td>
                        <td className="cell-wrap small">{t.run.project_name}</td>
                        <td className="cell-wrap">{t.name}<div className="small muted">{t.category || 'saved'}</div></td>
                        <td><span className={`status ${t.healed && t.status === 'PASSED' ? 'HEALED' : t.status}`}>{t.healed && t.status === 'PASSED' ? 'HEALED' : t.status}</span></td>
                        <td className="small cell-wrap">{t.error ? t.error.split('\n')[0] : '—'}</td>
                        <td className="small muted">{timeAgo(t.run.finished_at || t.run.started_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {results.length > shown && (
              <button type="button" className="btn btn-sm no-print self-center" onClick={() => setShown(shown + PAGE_SIZE)}>
                Show {Math.min(PAGE_SIZE, results.length - shown)} more
              </button>
            )}
          </section>
        </>
      )}
    </div>
  );
}
