/**
 * The repository's own unit tests in a run: its CI checks (with links to their
 * logs) or the sandbox run (framework, counts and the end of the output).
 */
import React from 'react';
import { CheckCircle2, CircleDashed, ExternalLink, FlaskConical, XCircle } from 'lucide-react';

const STATUS = {
  passed: { cls: 'pass', label: 'Passed' },
  failed: { cls: 'fail', label: 'Failed' },
  pending: { cls: 'warn', label: 'Still running' },
  none: { cls: 'muted', label: 'No tests found' },
  error: { cls: 'fail', label: 'Could not run' },
};

function CheckIcon({ state }) {
  if (state === 'passed') return <CheckCircle2 size={14} className="ok-text" aria-label="passed" />;
  if (state === 'failed') return <XCircle size={14} className="bad-text" aria-label="failed" />;
  return <CircleDashed size={14} className="muted" aria-label="running" />;
}

export default function RepositoryTests({ result }) {
  if (!result) return null;
  const status = STATUS[result.status] || STATUS.error;
  const fromCi = result.source === 'ci';
  return (
    <section className="card" aria-labelledby="repo-tests-title">
      <div className="card-head">
        <h3 id="repo-tests-title"><FlaskConical size={18} aria-hidden="true" />Repository tests</h3>
        <span className={`status ${status.cls}`}>{status.label}</span>
      </div>
      <p className="card-sub">
        {fromCi
          ? <>The repository&apos;s own CI on commit <span className="mono">{(result.commit || '').slice(0, 7)}</span>: {result.detail.replace(/^CI on \w+: /, '')}.</>
          : <>Run in an isolated sandbox (no network while testing, no access to this server): {result.detail.replace(/^Sandbox \([^)]*\): /, '')}.</>}
      </p>
      {fromCi && result.checks?.length > 0 && (
        <ul className="plain-list small">
          {result.checks.map((c) => (
            <li key={c.name} className="row">
              <CheckIcon state={c.state} />
              {c.url
                ? <a href={c.url} target="_blank" rel="noreferrer">{c.name} <ExternalLink size={12} aria-hidden="true" /></a>
                : <span>{c.name}</span>}
              {c.conclusion && c.state !== 'passed' && <span className="muted">{c.conclusion}</span>}
            </li>
          ))}
        </ul>
      )}
      {!fromCi && result.output && (
        <details open={result.status !== 'passed'}>
          <summary className="small">Test output ({result.framework})</summary>
          <pre className="udiff" tabIndex={0} aria-label="Repository test output">{result.output}</pre>
        </details>
      )}
    </section>
  );
}
