/**
 * API tokens: what a coding agent (the TestSphere MCP server) or a script sends
 * instead of a sign-in session, which expires after an hour.  A token acts as
 * the account until revoked; it is shown once, and only its hash is stored.
 */
import React, { useEffect, useState } from 'react';
import { Copy, KeyRound, Trash2 } from 'lucide-react';
import { createApiToken, getApiTokens, revokeApiToken } from '../services/api';
import { timeAgo } from '../lib/derive';

export default function ApiTokens() {
  const [tokens, setTokens] = useState(null);
  const [name, setName] = useState('');
  const [created, setCreated] = useState(null); // { name, token } just made, shown once
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    getApiTokens().then(setTokens).catch((err) => { setTokens([]); setError(err.message); });
  }, []);

  async function create(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const row = await createApiToken(name.trim());
      setCreated(row);
      setCopied(false);
      setTokens((prev) => [...(prev || []), row]);
      setName('');
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function revoke(row) {
    setError(null);
    try {
      await revokeApiToken(row.id);
      setTokens((prev) => prev.filter((t) => t.id !== row.id));
      if (created?.id === row.id) setCreated(null);
    } catch (err) {
      setError(`Could not revoke "${row.name}": ${err.message}`);
    }
  }

  return (
    <section className="card" aria-labelledby="tokens-title">
      <div className="card-head">
        <h3 id="tokens-title"><KeyRound size={18} aria-hidden="true" />API tokens</h3>
      </div>
      <p className="card-sub">
        For coding agents and scripts, such as the TestSphere MCP server in Claude Code, Cursor or Antigravity: set the
        token as <span className="mono">TESTSPHERE_TOKEN</span>. It acts as you until you revoke it here.
      </p>
      {created && (
        <div className="stack-sm" role="status">
          <div className="small"><b>{created.name}</b>: copy it now, it is not shown again.</div>
          <div className="row">
            <input className="input mono" readOnly value={created.token} aria-label="New API token"
              onFocus={(e) => e.target.select()} />
            <button type="button" className="btn btn-sm"
              onClick={() => navigator.clipboard?.writeText(created.token).then(() => setCopied(true))}>
              <Copy size={14} /> {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
        </div>
      )}
      {tokens?.length > 0 && (
        <ul className="plain-list small">
          {tokens.map((t) => (
            <li key={t.id} className="row-between">
              <span>
                <b>{t.name}</b> <span className="mono muted">{t.prefix}…</span>
                <span className="muted"> · made {timeAgo(t.created_at)} · {t.last_used_at ? `used ${timeAgo(t.last_used_at)}` : 'never used'}</span>
              </span>
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => revoke(t)}><Trash2 size={14} /> Revoke</button>
            </li>
          ))}
        </ul>
      )}
      <form className="form-row" onSubmit={create}>
        <label className="field wide">
          Name
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={60}
            placeholder="Claude Code MCP" required />
        </label>
        <button type="submit" className="btn btn-primary" disabled={busy || !name.trim()}>
          {busy ? 'Creating…' : 'Create token'}
        </button>
      </form>
      {error && <div className="error-text" role="alert">{error}</div>}
    </section>
  );
}
