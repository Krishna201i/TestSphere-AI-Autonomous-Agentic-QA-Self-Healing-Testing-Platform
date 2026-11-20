import React, { useState } from 'react';
import { Copy, Check } from 'lucide-react';
import { TIER_LABEL, findingTier } from '../lib/derive';

/** A finding's tier as a pill: Proven, Check by hand or Hardening. */
export function TierPill({ finding }) {
  const tier = TIER_LABEL[findingTier(finding)];
  return <span className={`pill ${tier.tone}`} title={tier.title}>{tier.text}</span>;
}

/** A command or value with a Copy button. */
export function CopyCommand({ command, label = 'Copy the command' }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }
  return (
    <div className="command">
      <code className="mono small">{command}</code>
      <button type="button" className="btn btn-sm btn-ghost" onClick={copy} aria-label={label}>
        {copied ? <Check size={13} /> : <Copy size={13} />} {copied ? 'Copied' : 'Copy'}
      </button>
    </div>
  );
}

/**
 * How to see a finding for yourself, and why it is rated as it is: what it
 * takes, numbered steps, the exact request, what came back, the code it is in.
 * Findings stored before these fields existed show only what they have.
 */
export default function FindingEvidence({ finding }) {
  if (!finding) return null;
  const { location, prerequisites, steps, request, response_excerpt: excerpt, severity_rationale: rationale,
    code_location: code } = finding;
  const where = location?.url ? `${location.method || 'GET'} ${location.url}${location.parameter ? ` · parameter ${location.parameter}` : ''}` : null;
  if (!where && !steps?.length && !request && !rationale) return null;
  return (
    <div className="evidence">
      <h4 className="section-title">How to reproduce</h4>
      <dl className="kv">
        {where && <><dt>Where</dt><dd className="mono small cell-wrap">{where}</dd></>}
        {code && <><dt>In the code</dt><dd className="mono small">{code}</dd></>}
        {prerequisites && <><dt>What it takes</dt><dd>{prerequisites}</dd></>}
      </dl>
      {steps?.length > 0 && (
        <ol className="steps small">
          {/* The command is shown once, in the copy box below */}
          {steps.map((s, i) => <li key={i} className="cell-wrap">{request ? s.replace(`: ${request}`, ' (command below)') : s}</li>)}
        </ol>
      )}
      {request && <CopyCommand command={request} />}
      {excerpt && (
        <>
          <div className="muted small">What came back</div>
          <pre className="excerpt mono small">{excerpt}</pre>
        </>
      )}
      {rationale && <p className="small"><b>Why {findingTier(finding) === 'hardening' ? 'it is not counted' : `${finding.severity}`}:</b> {rationale}</p>}
    </div>
  );
}
