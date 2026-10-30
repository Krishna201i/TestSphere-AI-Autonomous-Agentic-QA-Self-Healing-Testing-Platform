import { resultLabel, testDetail } from '../lib/derive';

/** A test's result badge, with Flaky and Quarantined beside it. */
export function ResultBadges({ test }) {
  const label = resultLabel(test);
  return (
    <span className="row">
      <span className={`status ${label}`}>{label}</span>
      {test.flaky && <span className="status FLAKY">Flaky</span>}
      {test.quarantined && <span className="pill gray">Quarantined</span>}
    </span>
  );
}

/** What a test checked (or why it failed), cut to three lines; the full text is in the tooltip and the run page. */
export function ResultDetail({ test }) {
  const d = testDetail(test);
  const why = test.status === 'FAILED' ? test.diagnosis : null;
  return (
    <>
      {why && <span className="pill red" title={why.next_step}>{why.label}</span>}
      <div className={`cell-clamp ${d.kind === 'error' ? 'text-danger' : ''}`} title={test.error || d.text}>{d.text}</div>
      {d.time && <div className="muted">{d.time}</div>}
    </>
  );
}

/** Why a test failed: the analyzer's diagnosis and what to do next. */
export function Diagnosis({ diagnosis }) {
  if (!diagnosis) return null;
  return (
    <div className="diagnosis" role="note" aria-label="Why it failed">
      <div className="row">
        <span className="pill red">{diagnosis.label}</span>
        {diagnosis.confidence && <span className="muted small">{diagnosis.confidence} confidence</span>}
      </div>
      {diagnosis.explanation && <p className="m-0">{diagnosis.explanation}</p>}
      {(diagnosis.expected || diagnosis.actual) && (
        <dl className="kv small">
          {diagnosis.expected && <><dt>Expected</dt><dd><code>{diagnosis.expected}</code></dd></>}
          {diagnosis.actual && <><dt>Actual</dt><dd><code>{diagnosis.actual}</code></dd></>}
        </dl>
      )}
      <p className="m-0 small"><b>Next step:</b> {diagnosis.next_step}</p>
    </div>
  );
}

/** The run in plain sentences (written from its results, not by a model). */
export function RunSummary({ lines, className = '' }) {
  if (!lines?.length) return null;
  return (
    <div className={`run-summary ${className}`} aria-label="Run summary">
      {lines.map((line) => <p key={line} className={`m-0 ${line.startsWith('Verdict:') ? 'run-verdict' : ''}`}>{line}</p>)}
    </div>
  );
}
