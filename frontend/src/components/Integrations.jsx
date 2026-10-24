/**
 * Integrations: connect GitHub with a fine-grained token so fix patches can
 * become pull requests and pushed commits get TestSphere's status.
 */
import React, { useEffect, useState } from 'react';
import { ExternalLink, GitPullRequest, Unplug } from 'lucide-react';
import { connectGitHub, disconnectGitHub, getIntegrations } from '../services/api';
import { timeAgo } from '../lib/derive';

const NEW_TOKEN_URL = 'https://github.com/settings/personal-access-tokens/new';

export default function Integrations() {
  const [github, setGithub] = useState(null);
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    getIntegrations()
      .then((rows) => setGithub(rows.find((r) => r.provider === 'github') || { connected: false }))
      .catch(() => setGithub({ connected: false }));
  }, []);

  async function connect(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setGithub(await connectGitHub(token.trim()));
      setToken('');
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    try {
      await disconnectGitHub();
      setGithub({ connected: false });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" aria-labelledby="integrations-title">
      <div className="card-head">
        <h3 id="integrations-title"><GitPullRequest size={18} aria-hidden="true" />Integrations</h3>
      </div>
      {!github && <div className="hint">Loading…</div>}
      {github?.connected && (
        <div className="row-between">
          <span className="row">
            {github.avatar_url && <img className="avatar" src={github.avatar_url} alt="" referrerPolicy="no-referrer" />}
            <span>GitHub connected as <b>{github.login}</b> <span className="muted small">· {timeAgo(github.connected_at)}</span></span>
          </span>
          <button type="button" className="btn btn-sm btn-ghost" onClick={disconnect} disabled={busy}><Unplug size={14} /> Disconnect</button>
        </div>
      )}
      {github?.connected && (
        <p className="hint m-0">Fix patches can now be opened as pull requests, and runs started by a push show their result on the commit.</p>
      )}
      {github && !github.connected && (
        <>
          <p className="card-sub">
            Connect GitHub to open pull requests from fix patches and show TestSphere's result on pushed commits.
          </p>
          <ol className="list small stack-sm">
            <li>
              <a href={NEW_TOKEN_URL} target="_blank" rel="noreferrer">Create a fine-grained token <ExternalLink size={12} className="icon-inline" /></a>{' '}
              with access to only the repositories you want.
            </li>
            <li>Under repository permissions, set <b>Contents</b>, <b>Pull requests</b> and <b>Commit statuses</b> to Read and write.</li>
            <li>Paste it here. It is checked with GitHub and stored encrypted; it is never shown again.</li>
          </ol>
          <form className="form-row" onSubmit={connect}>
            <label className="field wide">
              Personal access token
              <input className="input mono" type="password" value={token} onChange={(e) => setToken(e.target.value)}
                autoComplete="off" spellCheck={false} placeholder="github_pat_…" required minLength={20} />
            </label>
            <button type="submit" className="btn btn-primary" disabled={busy || token.trim().length < 20}>
              {busy ? 'Checking…' : 'Connect GitHub'}
            </button>
          </form>
          {error && <div className="error-text" role="alert">{error}</div>}
        </>
      )}
    </section>
  );
}
