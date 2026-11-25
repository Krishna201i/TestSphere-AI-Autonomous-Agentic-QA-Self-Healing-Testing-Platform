/**
 * The in-depth sections of a run page: the result bar, results by kind of
 * test and by page, what to do next, each analyzed page's audit, the
 * security findings, timing, and the stages with how long each took.
 * Everything comes from the run's own record (lib/runInsights.js).
 */
import React from 'react';
import { AlertTriangle, CheckCircle2, Clock, FileSearch, Gauge, Layers, ListChecks, ShieldAlert, XCircle } from 'lucide-react';
import { auditedPages, byKind, byPage, duration, recommendations, span, timing } from '../lib/runInsights';
import { StageIcon } from '../pages/Autopilot';
import { selectableRow } from '../lib/a11y';

/** Passed / healed / failed / quarantined as one stacked bar. */
export function ResultBar({ t, big = false, label }) {
  if (!t.total) return <div className={`result-bar ${big ? 'big' : ''}`} />;
  const seg = (cls, n) => n > 0 && <span className={cls} style={{ width: `${(100 * n) / t.total}%` }} />;
  return (
    <div className={`result-bar ${big ? 'big' : ''}`} role="img" aria-label={label || `${t.passed} of ${t.total} passed`}>
      {seg('seg-pass', t.passed - t.healed)}
      {seg('seg-heal', t.healed)}
      {seg('seg-fail', t.failed)}
      {seg('seg-quar', t.quarantined)}
    </div>
  );
}

export function ResultLegend() {
  return (
    <div className="result-legend xsmall muted" aria-hidden="true">
      <span><i className="seg-pass" />Passed</span>
      <span><i className="seg-heal" />Passed after self-healing</span>
      <span><i className="seg-fail" />Failed</span>
      <span><i className="seg-quar" />Failed, quarantined</span>
    </div>
  );
}

/** One row per kind of test: what it checks and how it went. Clicking a row filters the test list. */
export function KindTable({ tests, onPick }) {
  const rows = byKind(tests);
  if (!rows.length) return null;
  return (
    <section className="card" aria-labelledby="by-kind-title">
      <div className="card-head"><h3 id="by-kind-title"><Layers size={18} aria-hidden="true" /> Results by kind of test</h3><span className="muted small">{rows.length} kinds</span></div>
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>Kind</th><th className="num">Tests</th><th className="num">Passed</th><th className="num">Failed</th><th>Pass rate</th><th className="num">Avg time</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} className={onPick ? 'selectable' : ''} {...(onPick ? selectableRow(() => onPick(r.key), false) : {})}
                title={onPick ? `Show only ${r.label.toLowerCase()} tests` : undefined}>
                <td className="cell-wrap"><b>{r.label}</b><div className="small muted">{r.about}</div></td>
                <td className="num">{r.total}</td>
                <td className="num">{r.passed}{r.healed ? <span className="muted small"> ({r.healed} healed)</span> : null}</td>
                <td className="num">{r.failed}{r.quarantined ? <span className="muted small"> +{r.quarantined} quar.</span> : null}</td>
                <td className="bar-cell"><ResultBar t={r} /><span className="xsmall muted">{r.rate}%</span></td>
                <td className="num small nowrap">{duration(r.avg)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** One row per page the tests start on. */
export function PageTable({ tests }) {
  const rows = byPage(tests);
  if (rows.length <= 1 && rows[0]?.page === '(other)') return null;
  return (
    <section className="card" aria-labelledby="by-page-title">
      <div className="card-head"><h3 id="by-page-title"><FileSearch size={18} aria-hidden="true" /> Coverage by page</h3><span className="muted small">{rows.length} pages</span></div>
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>Page</th><th className="num">Tests</th><th className="num">Kinds</th><th className="num">Failed</th><th>Pass rate</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.page}>
                <td className="mono small cell-wrap">{r.page}</td>
                <td className="num">{r.total}</td>
                <td className="num">{r.kinds}</td>
                <td className="num">{r.failed + r.quarantined}</td>
                <td className="bar-cell"><ResultBar t={r} /><span className="xsmall muted">{r.rate}%</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** What to do next, most urgent first. */
export function Recommendations({ run, tests }) {
  const recs = recommendations(run, tests);
  if (!recs.length) return null;
  const Icon = { bad: XCircle, warn: AlertTriangle, ok: CheckCircle2 };
  return (
    <section className="card" aria-labelledby="recs-title">
      <div className="card-head"><h3 id="recs-title"><ListChecks size={18} aria-hidden="true" /> What to do next</h3><span className="muted small">{recs.length}</span></div>
      <ul className="rec-list">
        {recs.map((r) => {
          const I = Icon[r.level];
          return (
            <li key={r.title} className={`rec ${r.level}`}>
              <I size={16} aria-hidden="true" />
              <div className="min-w-0"><b>{r.title}</b><div className="small muted cell-wrap">{r.detail}</div></div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Score({ label, value, note }) {
  const v = Math.round(value || 0);
  const level = v >= 80 ? 'good' : v >= 50 ? 'warn' : 'bad';
  return (
    <div className="score-tile">
      <span className="xsmall muted">{label}</span>
      <span className={`score-v ${level}`}>{v}<span className="xsmall muted">/100</span></span>
      <span className={`meter ${level === 'good' ? 'good' : level === 'warn' ? 'warn' : ''}`}><span style={{ width: `${v}%` }} /></span>
      {note && <span className="xsmall muted cell-wrap">{note}</span>}
    </div>
  );
}

function Check({ ok, children }) {
  return <li className={ok ? 'check-yes' : 'check-no'}>{ok ? <CheckCircle2 size={14} aria-label="Yes" /> : <XCircle size={14} aria-label="No" />} {children}</li>;
}

const COUNT_LABELS = [['inputs', 'Fields'], ['buttons', 'Buttons'], ['forms', 'Forms'], ['links', 'Links'], ['headings', 'Headings'],
  ['images', 'Images'], ['hidden_controls', 'Hidden on load']];

/** One analyzed page: how it answered, what is on it, its health audit and headers. */
function PageCard({ page, start }) {
  const h = page.health || {};
  const sec = h.security || {};
  const a11y = h.accessibility || {};
  const perf = h.performance || {};
  const counts = page.counts || {};
  const headers = Object.entries(page.headers || {});
  return (
    <details className="subbox audit" open={start}>
      <summary>
        <span className="audit-title">{start && <span className="pill green">Start page</span>} <b className="cell-wrap">{page.title || page.url}</b></span>
        <span className="row small">
          <span className={`status ${page.status_code < 400 ? 'PASSED' : 'FAILED'}`}>HTTP {page.status_code}</span>
          <span className="muted">{page.latency_ms} ms</span>
          {h.overall_score != null && <span className="muted">health {h.overall_score}/100</span>}
        </span>
      </summary>
      <div className="stack">
        <div className="mono small muted cell-wrap">{page.url}{page.final_url && page.final_url !== page.url ? ` → ${page.final_url}` : ''}</div>
        {page.description && <p className="m-0 small">{page.description}</p>}
        <dl className="kv small audit-facts">
          <dt>First response</dt><dd>{page.latency_ms} ms</dd>
          <dt>HTML size</dt><dd>{page.html_kb ? `${page.html_kb} KB` : '—'}</dd>
          <dt>Language</dt><dd>{page.lang || <span className="text-danger">not declared</span>}</dd>
          <dt>Read in a browser</dt><dd>{page.rendered_in_browser ? 'yes' : 'no (HTML only)'}{page.visibility_checked ? ' · visibility checked' : ''}</dd>
        </dl>
        {h.overall_score != null && (
          <div className="score-grid">
            <Score label="Overall" value={h.overall_score} note="security 35% · accessibility 35% · performance 30%" />
            <Score label="Security" value={sec.score} note={sec.summary} />
            <Score label="Accessibility" value={a11y.score} note={a11y.status} />
            <Score label="Performance" value={perf.score} note={perf.rating} />
          </div>
        )}
        <div className="grid-2">
          {h.security && (
            <div>
              <h4 className="section-title">Security headers</h4>
              <ul className="audit-checks small">
                <Check ok={sec.is_https}>Served over HTTPS</Check>
                {sec.certificate_valid != null && <Check ok={sec.certificate_valid}>Valid TLS certificate</Check>}
                <Check ok={sec.hsts}>Strict-Transport-Security</Check>
                <Check ok={sec.csp}>Content-Security-Policy</Check>
                <Check ok={sec.x_frame_options}>X-Frame-Options (clickjacking)</Check>
                <Check ok={sec.x_content_type_options}>X-Content-Type-Options</Check>
              </ul>
            </div>
          )}
          {h.accessibility && (
            <div>
              <h4 className="section-title">Accessibility</h4>
              <ul className="audit-checks small">
                <Check ok={!a11y.missing_image_alts}>Images without alt text: {a11y.missing_image_alts || 0}</Check>
                <Check ok={!a11y.unlabeled_inputs}>Fields without a label: {a11y.unlabeled_inputs || 0}</Check>
                <Check ok={!a11y.unlabeled_buttons}>Buttons without text: {a11y.unlabeled_buttons || 0}</Check>
                <Check ok={Boolean(page.lang)}>Page language declared</Check>
              </ul>
            </div>
          )}
        </div>
        {Object.keys(counts).length > 0 && (
          <div className="stat-tiles">
            {COUNT_LABELS.filter(([k]) => counts[k] != null).map(([k, label]) => (
              <div key={k} className="stat-tile"><div className="v">{counts[k]}</div><div className="l">{label}</div></div>
            ))}
          </div>
        )}
        {page.headings?.length > 0 && (
          <div>
            <h4 className="section-title">Headings</h4>
            <ul className="plain-list small">{page.headings.map((x, i) => <li key={i} className="cell-wrap">{x}</li>)}</ul>
          </div>
        )}
        {headers.length > 0 && (
          <details className="small">
            <summary>Response headers ({headers.length})</summary>
            <table className="table"><tbody>
              {headers.map(([k, v]) => <tr key={k}><td className="mono xsmall">{k}</td><td className="mono xsmall cell-wrap">{v}</td></tr>)}
            </tbody></table>
          </details>
        )}
      </div>
    </details>
  );
}

/** Every page the run analyzed. */
export function PageAudit({ run }) {
  const pages = auditedPages(run);
  if (!pages.length) return null;
  return (
    <section className="card" aria-labelledby="pages-title">
      <div className="card-head"><h3 id="pages-title"><Gauge size={18} aria-hidden="true" /> Pages analyzed</h3><span className="muted small">{pages.length}</span></div>
      <p className="card-sub">How each page answered, what is on it, and its security, accessibility and performance audit. Open a page for its details.</p>
      <div className="stack">
        {pages.map((p, i) => <PageCard key={p.url || i} page={p} start={i === 0} />)}
      </div>
    </section>
  );
}

/** The scan's findings, most serious first. */
export function SecurityFindings({ run }) {
  const findings = run.security_findings;
  if (findings == null) return null;
  const tiers = { proven: 0, unconfirmed: 0, hardening: 0 };
  findings.forEach((f) => { tiers[f.tier] = (tiers[f.tier] || 0) + 1; });
  return (
    <section className="card" aria-labelledby="sec-title">
      <div className="card-head">
        <h3 id="sec-title"><ShieldAlert size={18} aria-hidden="true" /> Security findings</h3>
        <span className="row small">
          <span className="pill red">{tiers.proven} proven</span>
          <span className="pill orange">{tiers.unconfirmed} to check</span>
          <span className="pill gray">{tiers.hardening} hardening</span>
        </span>
      </div>
      {findings.length === 0 ? <div className="empty">The scan found nothing on the pages it checked.</div> : (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Severity</th><th>Finding</th><th>Evidence and fix</th></tr></thead>
            <tbody>
              {findings.map((f, i) => (
                <tr key={`${f.check_id}-${i}`}>
                  <td><span className={`sev ${f.severity}`}>{f.severity}</span><div className="xsmall muted">{f.tier}</div></td>
                  <td className="cell-wrap"><b>{f.title}</b><div className="xsmall muted mono">{f.check_id}</div><div className="xsmall muted">{f.component}</div></td>
                  <td className="small cell-wrap">
                    {f.evidence?.length > 0 && <ul className="plain-list">{f.evidence.map((e, j) => <li key={j}>{e}</li>)}</ul>}
                    {f.root_cause && <div><b>Why:</b> {f.root_cause}</div>}
                    {f.recommendation && <div><b>Fix:</b> {f.recommendation}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** Median, 90th percentile and the slowest tests. */
export function TimingCard({ tests, onOpen }) {
  const t = timing(tests);
  if (!t) return null;
  return (
    <section className="card" aria-labelledby="timing-title">
      <div className="card-head"><h3 id="timing-title"><Clock size={18} aria-hidden="true" /> Timing</h3></div>
      <div className="stat-tiles">
        <div className="stat-tile"><div className="v">{duration(t.total)}</div><div className="l">Test time, summed</div></div>
        <div className="stat-tile"><div className="v">{duration(t.median)}</div><div className="l">Median test</div></div>
        <div className="stat-tile"><div className="v">{duration(t.p90)}</div><div className="l">90th percentile</div></div>
        <div className="stat-tile"><div className="v">{duration(t.max)}</div><div className="l">Slowest test</div></div>
      </div>
      <h4 className="section-title">Slowest tests</h4>
      <ol className="plain-list slow-list small">
        {t.slowest.map((x) => (
          <li key={x.execution_id}>
            <button type="button" className="link-btn cell-wrap" onClick={() => onOpen?.(x.execution_id)}>{x.name}</button>
            <span className="muted nowrap">{duration(x.duration_ms)}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** The pipeline's stages, each with what happened and how long it took. */
export function StageTimeline({ stages }) {
  return (
    <ol className="stage-list" aria-label="Stages">
      {(stages || []).map((st) => {
        const took = span(st.started_at, st.finished_at);
        return (
          <li key={st.key} className={`stage-item ${st.status}`}>
            <StageIcon status={st.status} />
            <div className="min-w-0">
              <div className="stage-label">{st.label}{took != null && <span className="muted xsmall"> · {duration(took)}</span>}</div>
              {st.detail && <div className="small muted cell-wrap">{st.detail}</div>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
