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
  return (
    <>
      <div className={`cell-clamp ${d.kind === 'error' ? 'text-danger' : ''}`} title={test.error || d.text}>{d.text}</div>
      {d.time && <div className="muted">{d.time}</div>}
    </>
  );
}
