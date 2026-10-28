/**
 * Integrations: connect GitHub so private repositories can be fetched, fix
 * patches become pull requests and pushed commits get TestSphere's status.
 * Signed-in users connect with a GitHub window; anyone can paste a
 * fine-grained token (limited to chosen repositories) instead.
 */
import React, { useEffect, useState } from 'react';
import { ExternalLink, GitPullRequest, Github, KeyRound, Trash2, Unplug } from 'lucide-react';
import {
  connectGitHub, deleteGitCredential, disconnectGitHub, getGitCredentials, getIntegrations, saveGitCredential,
} from '../services/api';
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
    setError(null);
    try {
      await disconnectGitHub();
      setGithub({ connected: false });
    } catch (err) {
      setError(`Could not disconnect GitHub: ${err.message}`);
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
      {github?.connected && error && <div className="error-text" role="alert">{error}</div>}
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
      <GitCredentials />
    </section>
  );
}

/** Tokens for private repositories on GitLab, Bitbucket and other allowed Git hosts. */
function GitCredentials() {
  const [rows, setRows] = useState(null);
  const [form, setForm] = useState({ host: '', username: '', token: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    getGitCredentials().then(setRows).catch(() => setRows([]));
  }, []);

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const saved = await saveGitCredential({
        host: form.host.trim(), username: form.username.trim() || null, token: form.token.trim(),
      });
      setRows((prev) => [...(prev || []).filter((r) => r.host !== saved.host), saved]);
      setForm({ host: '', username: '', token: '' });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(host) {
    setError(null);
    try {
      await deleteGitCredential(host);
      setRows((prev) => prev.filter((r) => r.host !== host));
    } catch (err) {
      setError(`Could not remove the credential for ${host}: ${err.message}`);
    }
  }

  return (
    <div className="stack-sm">
      <h4 className="section-title mt-3"><KeyRound size={14} aria-hidden="true" /> Other Git hosts</h4>
      <p className="hint m-0">
        For private repositories on GitLab, Bitbucket or a self-hosted Git server: save an access token with read access
        for the host (with write access on gitlab.com or bitbucket.org, fix patches also open as merge or pull requests).
        It is stored encrypted and never shown again.
      </p>
      {rows?.length > 0 && (
        <ul className="plain-list small">
          {rows.map((r) => (
            <li key={r.host} className="row-between">
              <span><b>{r.host}</b> <span className="muted">· {r.username}{r.added_at ? ` · ${timeAgo(r.added_at)}` : ''}</span></span>
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => remove(r.host)}>
                <Trash2 size={14} /> Remove
              </button>
            </li>
          ))}
        </ul>
      )}
      <form className="form-row" onSubmit={save}>
        <label className="field">
          Host
          <input className="input" value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })}
            placeholder="gitlab.com" required minLength={3} />
        </label>
        <label className="field">
          User name <span className="muted">(optional)</span>
          <input className="input" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })}
            autoComplete="off" placeholder="Bitbucket needs yours" />
        </label>
        <label className="field wide">
          Access token
          <input className="input mono" type="password" value={form.token} onChange={(e) => setForm({ ...form, token: e.target.value })}
            autoComplete="off" spellCheck={false} required minLength={8} />
        </label>
        <button type="submit" className="btn" disabled={busy || !form.host.trim() || form.token.trim().length < 8}>
          {busy ? 'Saving…' : 'Save credential'}
        </button>
      </form>
      {error && <div className="error-text" role="alert">{error}</div>}
    </div>
  );
}
