import React, { useEffect, useState } from 'react';
import { LogOut, Save } from 'lucide-react';
import { useAuth } from '../state/Auth';
import { useWorkspace } from '../state/Workspace';
import { getMe, updateMe } from '../services/api';
import { timeAgo, toDate } from '../lib/derive';

const PROVIDERS = { password: 'Email & password', 'google.com': 'Google', local: 'Local (sign-in off)' };

export function initialsOf(name) {
  return (name || '').split(/[\s._@-]+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('') || '?';
}

export default function Profile({ onNavigate }) {
  const auth = useAuth();
  const { refresh, setOperator } = useWorkspace();
  const [me, setMe] = useState(null);
  const [form, setForm] = useState({ display_name: '', organization: '', job_title: '' });
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getMe().then((data) => {
      setMe(data);
      setForm({ display_name: data.display_name || '', organization: data.organization || '', job_title: data.job_title || '' });
    }).catch((err) => setError(err.message));
  }, []);

  async function onSave(e) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const data = await updateMe(form);
      setMe(data);
      if (data.local && data.display_name) setOperator(data.display_name);
      setSaved(true);
      refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  const name = me?.display_name || auth.user?.name || auth.user?.email || 'You';
  const stats = me?.stats;

  return (
    <div className="page">
      <div className="page-title">
        <div>
          <h1>Profile</h1>
          <p>Your account, your workspace activity, and how you appear in the audit trail.</p>
        </div>
        {auth.mode === 'firebase' && (
          <button type="button" className="btn" onClick={auth.signOut}><LogOut size={16} /> Sign out</button>
        )}
      </div>

      {error && <div className="alert-banner" role="alert" style={{ margin: 0 }}>{error}</div>}

      <div className="grid-main-side">
        <section className="card">
          <div className="profile-head">
            {me?.photo_url
              ? <img className="avatar avatar-lg" src={me.photo_url} alt="" referrerPolicy="no-referrer" />
              : <span className="avatar avatar-lg">{initialsOf(name)}</span>}
            <div style={{ minWidth: 0 }}>
              <div className="profile-name">{name}</div>
              <div className="muted cell-wrap">{me?.email || (me?.local ? 'Sign-in is off on this server — single local user' : '')}</div>
            </div>
          </div>
          <form className="auth-form" onSubmit={onSave}>
            <label className="field">
              Display name (shown on approvals, scans and pipeline runs)
              <input className="input" value={form.display_name} maxLength={80}
                onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
            </label>
            <div className="form-row">
              <label className="field">
                Organization
                <input className="input" value={form.organization} maxLength={120}
                  onChange={(e) => setForm({ ...form, organization: e.target.value })} />
              </label>
              <label className="field">
                Job title
                <input className="input" value={form.job_title} maxLength={80}
                  onChange={(e) => setForm({ ...form, job_title: e.target.value })} />
              </label>
            </div>
            <div className="form-row" style={{ alignItems: 'center' }}>
              <button type="submit" className="btn btn-primary" disabled={saving || !me}><Save size={16} /> {saving ? 'Saving…' : 'Save profile'}</button>
              {saved && <span className="ok-text small">Saved.</span>}
            </div>
          </form>
        </section>

        <section className="card">
          <div className="card-head"><h3>Account</h3></div>
          <dl className="kv">
            <dt>Sign-in</dt><dd>{PROVIDERS[me?.provider] || me?.provider || '—'}</dd>
            <dt>User ID</dt><dd className="mono small">{me?.uid || '—'}</dd>
            <dt>Member since</dt><dd>{me?.member_since ? toDate(me.member_since).toLocaleDateString() : '—'}</dd>
            <dt>Last sign-in</dt><dd>{me?.last_login_at ? timeAgo(me.last_login_at) : '—'}</dd>
          </dl>
          <div className="stat-tiles">
            <div className="stat-tile"><div className="v">{stats?.projects ?? '—'}</div><div className="l">Projects</div></div>
            <div className="stat-tile"><div className="v">{stats?.pipeline_runs ?? '—'}</div><div className="l">Pipeline runs</div></div>
            <div className="stat-tile"><div className="v">{stats?.test_executions ?? '—'}</div><div className="l">Test executions</div></div>
            <div className="stat-tile"><div className="v">{stats?.open_findings ?? '—'}</div><div className="l">Open findings</div></div>
          </div>
          {stats?.last_run && (
            <div className="small">
              Last pipeline: <span className={`status run-${stats.last_run.status}`}>{stats.last_run.status}</span>{' '}
              #{stats.last_run.id} · {stats.last_run.project_name}
              {stats.last_run.finished_at ? ` · ${timeAgo(stats.last_run.finished_at)}` : ''}
            </div>
          )}
          <div className="popover-links">
            <button type="button" className="tab" onClick={() => onNavigate('automation')}>Automation</button>
            <button type="button" className="tab" onClick={() => onNavigate('audit', { query: name })}>My activity</button>
          </div>
        </section>
      </div>
    </div>
  );
}
