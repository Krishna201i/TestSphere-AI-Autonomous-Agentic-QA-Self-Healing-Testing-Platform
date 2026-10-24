import React, { useState } from 'react';
import { CheckCircle2, Check, Clock3 } from 'lucide-react';
import { useWorkspace } from '../state/Workspace';
import { timeAgo } from '../lib/derive';

/**
 * Two-column diff: observed (removed + context) vs proposed (added + context).
 * Changed lines come first, so the fix is visible without scrolling; unchanged
 * headers follow as context.
 */
export function DiffView({ diff, leftTitle = 'Observed', rightTitle = 'Proposed fix', contextLines = 4, stacked = false }) {
  const context = diff.filter((d) => d.kind === 'context');
  const removed = diff.filter((d) => d.kind === 'removed');
  const added = diff.filter((d) => d.kind === 'added');
  const shown = context.slice(0, contextLines);
  const hidden = context.length - shown.length;

  const col = (title, changed, mark, placeholder) => (
    <div className="diff-col">
      <div className="diff-title">{title}</div>
      <div className="diff-lines" tabIndex={0} role="region" aria-label={title}>
        {changed.length === 0 && placeholder && (
          <div className="diff-line removed"><span className="ln" /><span>−</span><span>{placeholder}</span></div>
        )}
        {[...changed, ...shown].map((d, i) => (
          <div key={i} className={`diff-line ${d.kind}`}>
            <span className="ln">{i + 1}</span>
            <span>{d.kind === mark ? (mark === 'added' ? '+' : '−') : ''}</span>
            <span>{d.text}</span>
          </div>
        ))}
        {hidden > 0 && <div className="diff-more">… {hidden} more unchanged header(s)</div>}
      </div>
    </div>
  );
  // A missing header has nothing to remove: say so explicitly on the left
  const missing = removed.length === 0 && added.length ? `${added.map((a) => a.text.split(':')[0]).join(', ')} (not sent)` : null;
  return (
    <div className={`diff ${stacked ? 'stacked' : ''}`}>
      {col(leftTitle, removed, 'removed', missing)}
      {col(rightTitle, added, 'added')}
    </div>
  );
}

/** Picks the selected (or first) finding that has a concrete header/cookie proposal. */
export function useSelectedProposal() {
  const { lastScan, selectedKey } = useWorkspace();
  const proposals = (lastScan?.findings || []).filter((f) => f.remediation?.kind === 'header');
  return proposals.find((f) => f.key === selectedKey) || proposals[0] || null;
}

export function ApprovalControls({ finding }) {
  const { approvals, approve, retests, retest, retesting } = useWorkspace();
  const [error, setError] = useState(null);
  const approval = approvals[finding.key];
  const result = retests[finding.key];
  const resolved = result?.result === 'pass';

  async function onApprove() {
    setError(null);
    try {
      await approve(finding);
    } catch (e) {
      setError(e.message);
    }
  }

  async function onRetest() {
    setError(null);
    try {
      await retest(finding);
    } catch (e) {
      setError(e.message);
    }
  }

  let state = <><Clock3 size={16} /> Waiting for approval</>;
  if (resolved) state = <span className="row ok-text"><CheckCircle2 size={16} /> Retest passed, resolved <Check size={14} /></span>;
  else if (approval) state = <span className="row ok-text"><CheckCircle2 size={16} /> Approved by {approval.by} · {timeAgo(approval.at)}</span>;

  return (
    <div className="approve-box">
      <div className="approve-row">
        <span className="title">Fix status</span>
        <span className="state">{state}</span>
      </div>
      {!approval && (
        <button type="button" className="btn btn-primary btn-block" onClick={onApprove}>
          Approve fix
        </button>
      )}
      {approval && !resolved && (
        <>
          <button type="button" className="btn btn-primary btn-block" onClick={onRetest} disabled={retesting === finding.key}>
            {retesting === finding.key ? 'Retesting…' : 'Run retest'}
          </button>
          <span className="hint">
            Apply the approved config on the target (ready-to-paste snippets are in the Remediation Bridge), then retest.
            {result?.result === 'fail' && ` Last retest ${timeAgo(result.at)}: still reproduces.`}
          </span>
        </>
      )}
      {resolved && (
        <button type="button" className="btn btn-block" disabled>Resolved: the retest verified the fix</button>
      )}
      {error && <span className="error-text">{error}</span>}
    </div>
  );
}

export default function RemediationCard({ onOpen }) {
  const finding = useSelectedProposal();
  const { operator } = useWorkspace();
  return (
    <section className="card" aria-labelledby="remediation-title">
      <div className="card-head">
        <h3 id="remediation-title">Fix proposals</h3>
        {finding && <span className={`sev ${finding.severity}`}>{finding.severity}</span>}
      </div>

      {finding ? (
        <>
          <p className="card-sub cell-wrap">{finding.title}</p>
          <div className="subbox flush">
            <div className="approval-head">Needs your approval · <span className="mono">{finding.check_id}</span></div>
            <DiffView diff={finding.remediation.diff} stacked />
          </div>
          <ApprovalControls finding={finding} />
        </>
      ) : (
        <div className="empty">
          <span className="empty-title">No fixes to approve</span>
          Proposals appear when a scan finds header or cookie issues.
          <button type="button" className="btn btn-sm" onClick={onOpen}>Open security</button>
        </div>
      )}
      <div className="card-foot">
        <span className="small muted">Signed as {operator}. Approvals and retests are recorded in Audit.</span>
      </div>
    </section>
  );
}
