import React, { useEffect, useState } from 'react';
import { Copy, Share2, X } from 'lucide-react';
import { createRunShare, getRunShares, revokeRunShare } from '../services/api';
import { toDate } from '../lib/derive';

/**
 * Read-only links to one run's report, for people without an account.
 * A new link is shown once (only its hash is kept); links expire and can be revoked.
 */
export default function ShareReport({ runId }) {
  const [links, setLinks] = useState([]);
  const [fresh, setFresh] = useState(null);  // the link just created: the only time its URL is known
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getRunShares(runId).then(setLinks).catch(() => setLinks([]));
  }, [runId]);

  async function create() {
    setBusy(true); setError(null); setCopied(false);
    try {
      const link = await createRunShare(runId, 7);
      setFresh(link);
      setLinks((prev) => [link, ...prev]);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function revoke(id) {
    setError(null);
    try {
      await revokeRunShare(id);
      setLinks((prev) => prev.map((l) => (l.id === id ? { ...l, revoked: true, active: false } : l)));
      if (fresh?.id === id) setFresh(null);
    } catch (err) {
      setError(err.message);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(fresh.url);
      setCopied(true);
    } catch {
      setError('Copy failed: select the link and copy it.');
    }
  }

  const active = links.filter((l) => l.active);
  return (
    <section className="card" aria-labelledby="share-title">
      <div className="card-head">
        <h3 id="share-title"><Share2 size={18} /> Share this report</h3>
        <button type="button" className="btn btn-sm" onClick={create} disabled={busy}>{busy ? 'Creating…' : 'Create read-only link'}</button>
      </div>
      <p className="hint m-0">Anyone with the link sees this run's report (summary, failures with screenshots, all tests) for 7 days, without signing in. Nothing else of your account is visible. You can revoke it at any time.</p>
      {fresh && (
        <div className="share-fresh">
          <label className="small muted" htmlFor="share-url">Copy it now: for safety it is shown only once.</label>
          <div className="row">
            <input id="share-url" className="input" readOnly value={fresh.url} onFocus={(e) => e.target.select()} />
            <button type="button" className="btn btn-sm" onClick={copy}><Copy size={14} /> {copied ? 'Copied' : 'Copy'}</button>
          </div>
        </div>
      )}
      {error && <div className="alert-banner inline" role="alert">{error}</div>}
      {active.length > 0 && (
        <ul className="plain-list">
          {active.map((l) => (
            <li key={l.id} className="row small">
              <span>Link #{l.id} · expires {toDate(l.expires_at).toLocaleString()}{l.created_by ? ` · made by ${l.created_by}` : ''}</span>
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => revoke(l.id)} aria-label={`Revoke link ${l.id}`}><X size={14} /> Revoke</button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
