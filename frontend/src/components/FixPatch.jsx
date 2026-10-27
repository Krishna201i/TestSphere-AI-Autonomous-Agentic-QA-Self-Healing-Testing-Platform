/**
 * Fix patch: the site's open findings as a unified diff against its own
 * repository, file by file, with the fixes it makes and the ones it cannot.
 */
import React, { useEffect, useState } from 'react';
import { CheckCircle2, Copy, Download, ExternalLink, FileDiff, GitBranch, GitPullRequest, TriangleAlert } from 'lucide-react';
import { useWorkspace } from '../state/Workspace';
import { createFixPatch, downloadFixPatch, getFixPatches, openPullRequest } from '../services/api';
import { timeAgo } from '../lib/derive';

const hostOf = (url) => {
  try {
    return new URL(url).host.toLowerCase();
  } catch {
    return '';
  }
};

/** A unified diff, one row per line, coloured by kind. */
export function UnifiedDiff({ text, label }) {
  const lines = text.replace(/\n$/, '').split('\n');
  return (
    <pre className="udiff" tabIndex={0} aria-label={label}>
      {lines.map((line, i) => {
        const kind = line.startsWith('+++') || line.startsWith('---') ? 'file'
          : line.startsWith('@@') ? 'hunk' : line.startsWith('+') ? 'add' : line.startsWith('-') ? 'del' : 'ctx';
        return <span key={i} className={`ud-${kind}`}>{line || ' '}{'\n'}</span>;
      })}
    </pre>
  );
}

function saveBlob(blob, name) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function PullRequestButton({ patch, onOpened }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  if (patch.pull_request) {
    return (
      <a className="btn btn-sm" href={patch.pull_request.url} target="_blank" rel="noreferrer">
        <GitPullRequest size={14} /> Pull request #{patch.pull_request.number} <ExternalLink size={12} />
      </a>
    );
  }
  if (!patch.github || patch.files.length === 0) return null;
  async function open() {
    setBusy(true);
    setError(null);
    try {
      onOpened(await openPullRequest(patch.id));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <button type="button" className="btn btn-sm btn-primary" onClick={open} disabled={busy}>
        <GitPullRequest size={14} /> {busy ? 'Opening…' : 'Open pull request'}
      </button>
      {error && <span className="error-text" role="alert">{error}</span>}
    </>
  );
}

function PatchView({ patch, onPullRequest }) {
  const [copied, setCopied] = useState(false);
  const [downloadError, setDownloadError] = useState(null);
  const file = `testsphere-fix-${patch.id}.patch`;
  return (
    <div className="stack">
      <div className="row-between">
        <span className="row small">
          {patch.frameworks.map((f) => <span key={f} className="pill blue">{f}</span>)}
          <span className="muted"><GitBranch size={13} className="icon-inline" /> {patch.repo}{patch.commit ? ` @ ${patch.commit.slice(0, 7)}` : ''} · {timeAgo(patch.created_at)}</span>
        </span>
        {patch.files.length > 0 && (
          <span className="row">
            <PullRequestButton patch={patch} onOpened={onPullRequest} />
            <button type="button" className="btn btn-sm" onClick={() => { setDownloadError(null); downloadFixPatch(patch.id).then((b) => saveBlob(b, file)).catch((err) => setDownloadError(`Download failed: ${err.message}`)); }}><Download size={14} /> Download .patch</button>
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => navigator.clipboard?.writeText(patch.patch).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); })}>
              <Copy size={14} /> {copied ? 'Copied' : 'Copy'}
            </button>
          </span>
        )}
      </div>
      {downloadError && <div className="error-text" role="alert">{downloadError}</div>}

      {patch.applied.length > 0 && (
        <ul className="plain-list small">
          {patch.applied.map((a, i) => (
            <li key={i} className="row"><CheckCircle2 size={14} className="ok-text" aria-hidden="true" /><span className="mono">{a.check_id}</span> {a.how} <span className="muted">in {a.file}</span></li>
          ))}
        </ul>
      )}
      {patch.manual.length > 0 && (
        <div className="subbox tinted">
          <h4>Needs a change by hand</h4>
          <ul className="plain-list small">
            {patch.manual.map((m, i) => (
              <li key={i} className="row"><TriangleAlert size={14} className="warn-text" aria-hidden="true" /><span className="mono">{m.check_id}</span> <span className="cell-wrap">{m.reason}</span></li>
            ))}
          </ul>
        </div>
      )}

      {patch.files.map((f) => (
        <div key={f.path} className="subbox flush">
          <div className="approval-head row-between">
            <span className="row"><FileDiff size={15} aria-hidden="true" /> <span className="mono">{f.path}</span></span>
            {f.verified === true && <span className="status pass">still parses</span>}
            {f.verified === false && <span className="status fail" title={f.check_note || ''}>syntax error</span>}
            {f.verified == null && <span className="muted xsmall">not syntax-checked</span>}
          </div>
          {f.check_note && <div className="small bad-text approval-note">{f.check_note}</div>}
          <UnifiedDiff text={f.diff} label={`Changes to ${f.path}`} />
        </div>
      ))}
      {patch.files.length > 0 && (
        <p className="hint m-0">
          Review it, then in your repository run <code>git apply {file}</code>, deploy, and retest the findings in Validation.
        </p>
      )}
    </div>
  );
}

export default function FixPatchCard({ targetUrl }) {
  const { projects, refresh } = useWorkspace();
  const linked = projects.find((p) => p.repo_url && hostOf(p.app_url) === hostOf(targetUrl));
  const [repo, setRepo] = useState('');
  const [patches, setPatches] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!targetUrl) return;
    getFixPatches(targetUrl).then(setPatches).catch(() => setPatches([]));
  }, [targetUrl]);

  async function generate(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await createFixPatch({ target_url: targetUrl, repo: repo.trim() || null });
      setPatches((prev) => [created, ...prev]);
      refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const latest = patches[0];
  return (
    <section className="card" aria-labelledby="patch-title">
      <div className="card-head">
        <h3 id="patch-title"><FileDiff size={18} aria-hidden="true" />Fix patch for your code</h3>
        <span className="pill violet">4 · Remediation</span>
      </div>
      <p className="card-sub">
        Turns the open findings for {hostOf(targetUrl) || 'this site'} into a patch against the repository: header middleware,
        CORS allow-list and cookie flags in FastAPI, Flask, Django, Express or nginx. Your repository is read, never changed.
      </p>
      <form className="form-row" onSubmit={generate}>
        <label className="field wide">
          Repository
          <input className="input" value={repo} onChange={(e) => setRepo(e.target.value)}
            placeholder={linked ? `${linked.repo_url} (from project ${linked.name})` : 'https://github.com/you/app'} />
        </label>
        <button type="submit" className="btn btn-primary" disabled={busy || (!repo.trim() && !linked)}>
          {busy ? 'Building patch…' : 'Generate patch'}
        </button>
      </form>
      {!linked && !repo && <div className="hint">Link a repository to the site's project in Autopilot, or paste one here.</div>}
      {busy && <div className="hint">Cloning the repository and editing a temporary copy…</div>}
      {error && <div className="error-text" role="alert">{error}</div>}
      {latest && <PatchView patch={latest} onPullRequest={(pr) => setPatches((prev) => prev.map((p) => (p.id === latest.id ? { ...p, pull_request: pr } : p)))} />}
      {patches.length > 1 && (
        <details className="small">
          <summary>Earlier patches ({patches.length - 1})</summary>
          <ul className="plain-list">
            {patches.slice(1).map((p) => (
              <li key={p.id}>
                <button type="button" className="link-btn" onClick={() => downloadFixPatch(p.id).then((b) => saveBlob(b, `testsphere-fix-${p.id}.patch`)).catch((err) => setError(`Download of patch #${p.id} failed: ${err.message}`))}>
                  #{p.id}
                </button> · {p.files.length} file(s) · {timeAgo(p.created_at)}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
