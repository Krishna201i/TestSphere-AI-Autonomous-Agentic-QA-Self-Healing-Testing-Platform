/**
 * Integrations: connect GitHub so private repositories can be fetched, fix
 * patches become pull requests and pushed commits get TestSphere's status.
 * Signed-in users connect with a GitHub window; anyone can paste a
 * fine-grained token (limited to chosen repositories) instead.
 */
import React, { useEffect, useState } from 'react';
import { ExternalLink, GitPullRequest, Github, Unplug } from 'lucide-react';
import { connectGitHub, disconnectGitHub, getIntegrations } from '../services/api';
import { timeAgo } from '../lib/derive';
import { authMessage, useAuth } from '../state/Auth';

const NEW_TOKEN_URL = 'https://github.com/settings/personal-access-tokens/new';

export default function Integrations() {
  const [github, setGithub] = useState(null);
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const { user, githubRepoToken } = useAuth();
  const canUseWindow = Boolean(user && user.provider !== 'local');

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

  async function connectWithWindow() {
    setBusy(true);
    setError(null);
    try {
      const granted = await githubRepoToken();
      if (!granted) throw new Error('GitHub did not return access. Try again, or paste a token below.');
      setGithub(await connectGitHub(granted));
    } catch (err) {
      setError(err.code ? authMessage(err) : err.message);
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
            Connect GitHub to test private repositories, open pull requests from fix patches and show TestSphere's
            result on pushed commits.
          </p>
          {canUseWindow && (
            <>
              <button type="button" className="btn btn-primary" onClick={connectWithWindow} disabled={busy}>
                <Github size={16} aria-hidden="true" /> {busy ? 'Connecting…' : 'Connect with GitHub'}
              </button>
              <p className="hint m-0">GitHub asks you to allow access to your repositories. Prefer access to only some of them? Use a token instead:</p>
            </>
          )}
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
