import React, { useEffect, useState } from 'react';
import { addScanTarget, getScanTargets, removeScanTarget, verifyScanTarget } from '../services/api';
import { CopyCommand } from './FindingEvidence';
import { timeAgo, urlError } from '../lib/derive';

const STATE = {
  verified: { text: 'Verified', tone: 'green' },
  pending: { text: 'Waiting for proof', tone: 'orange' },
  expired: { text: 'Proof expired', tone: 'red' },
  no_proof_needed: { text: 'Allowed (no proof needed here)', tone: 'blue' },
};

/** Why this account cannot run active scans yet, in words a person can act on; null when it can. */
function blocker(status) {
  if (!status) return null;
  if (!status.server) {
    return 'Active scanning is turned off on this server. An administrator turns it on with SECURITY_ACTIVE_SCAN=true.';
  }
  if (!status.allowed) return `${status.reason}.`;
  return null;
}

/**
 * Sites for active testing: add a site, publish the token TestSphere gives
 * it, verify, and active scans of that site are allowed for 30 days.
 * *onPick* puts a ready site in the scan form.
 */
export default function ActiveTargets({ onPick }) {
  const [data, setData] = useState(null);
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(null); // 'add' or a site id
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  async function load() {
    try {
      setData(await getScanTargets());
    } catch (err) {
      setError(err.message);
    }
  }
  useEffect(() => { load(); }, []);

  async function act(key, fn, done) {
    setError(null);
    setNotice(null);
    setBusy(key);
    try {
      const result = await fn();
      if (done) setNotice(done(result));
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  }

  function onAdd(e) {
    e.preventDefault();
    const bad = urlError(url.trim());
    if (bad) {
      setError(bad);
      return;
    }
    act('add', () => addScanTarget(url.trim()), (t) => `Added ${t.host}.`).then(() => setUrl(''));
  }

  const targets = data?.targets || [];
  const block = blocker(data?.active_scan);
  return (
    <section className="card" aria-labelledby="active-targets-title">
      <div className="card-head">
        <h3 id="active-targets-title">Sites for active testing</h3>
        <span className="muted small">{targets.length}</span>
      </div>
      <p className="card-sub">
        Active scans send test attacks, so they run only on sites you prove you own: add the site, publish the
        token below on it, then verify. A verified site can be scanned actively for 30 days.
      </p>
      {block && (
        <div className="hint">
          {block}
          {data?.active_scan?.server && data.active_scan.uid && !data.active_scan.allowed && (
            <div className="mt-2">
              Your account id, for SECURITY_ACTIVE_SCAN_USERS:
              <CopyCommand command={data.active_scan.uid} label="Copy your account id" />
            </div>
          )}
        </div>
      )}
      <form className="form-row" onSubmit={onAdd}>
        <label className="field wide">
          Site address
          <input className="input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://staging.your-app.com" />
        </label>
        <button className="btn" type="submit" disabled={busy === 'add'}>{busy === 'add' ? 'Adding…' : 'Add site'}</button>
      </form>
      {error && <div className="error-text" role="alert">{error}</div>}
      {notice && <div className="hint" role="status">{notice}</div>}
      {data && targets.length === 0 && <div className="empty">No sites yet. Passive scans work on any public site without adding it.</div>}
      {targets.length > 0 && (
        <ul className="plain-list">
          {targets.map((t) => {
            const state = STATE[t.state] || STATE.pending;
            const ready = t.state === 'verified' || t.state === 'no_proof_needed';
            return (
              <li key={t.id} className="subbox">
                <div className="row target-head">
                  <b className="mono">{t.host}</b>
                  <span className={`pill ${state.tone}`}>{state.text}</span>
                  {t.state === 'verified' && t.verified_at && <span className="muted small">verified {timeAgo(t.verified_at)}</span>}
                  <span className="row ml-auto">
                    {ready && onPick && (
                      <button type="button" className="btn btn-sm" onClick={() => onPick(t.url)}>Scan it</button>
                    )}
                    {t.needs_proof && (
                      <button type="button" className="btn btn-sm" disabled={busy === t.id}
                        onClick={() => act(t.id, () => verifyScanTarget(t.id), (r) => r.message)}>
                        {busy === t.id ? 'Checking…' : t.state === 'verified' ? 'Verify again' : 'Verify'}
                      </button>
                    )}
                    <button type="button" className="btn btn-sm btn-ghost" disabled={busy === t.id}
                      onClick={() => act(t.id, () => removeScanTarget(t.id), () => `Removed ${t.host}.`)}>
                      Remove
                    </button>
                  </span>
                </div>
                {t.needs_proof && t.state !== 'verified' && (
                  <div className="small target-proof">
                    <div>1. On the site, publish a file at this address:</div>
                    <CopyCommand command={t.file_url} label={`Copy the file address for ${t.host}`} />
                    <div>2. Its content is this token (a line of its own):</div>
                    <CopyCommand command={t.token} label={`Copy the token for ${t.host}`} />
                    <div>3. Press Verify. Redirects are not followed, so the file must be served at exactly that address.</div>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
