import React, { useState } from 'react';
import { CheckCircle2, LogIn, RefreshCw, ShieldCheck, Stethoscope, UserPlus, Wand2 } from 'lucide-react';
import { authMessage, useAuth } from '../state/Auth';
import { Logo } from '../components/TopNav';
import { API_BASE_LABEL } from '../services/api';

function Brand() {
  return (
    <div className="auth-brand">
      <Logo size={32} />
      <span className="brand-name">TestSphere <b>AI</b></span>
    </div>
  );
}

/** The product side of the sign-in screen: what TestSphere does, as a small loop. */
function MiniLoop() {
  const labels = [['Ingest', 60, 40], ['Test', 220, 40], ['Report', 380, 40], ['Fix', 380, 160], ['Verify', 220, 160], ['Deploy', 60, 160]];
  return (
    <svg className="mini-loop" viewBox="0 0 440 200" aria-hidden="true">
      <rect className="ml-track" x="40" y="40" width="360" height="120" rx="60" />
      <rect className="ml-progress" x="40" y="40" width="360" height="120" rx="60" />
      {labels.map(([label, x, y]) => (
        <g key={label}>
          <circle className="ml-node" cx={x} cy={y} r="7" />
          <text className="ml-text" x={x} y={y < 100 ? y - 16 : y + 26} textAnchor="middle">{label}</text>
        </g>
      ))}
    </svg>
  );
}

function AuthShell({ children }) {
  return (
    <div className="auth-screen">
      <main className="auth-main">
        <div className="auth-panel">
          <Brand />
          {children}
        </div>
      </main>
      <aside className="auth-aside" aria-label="About TestSphere AI">
        <div>
          <h2>Tests that repair themselves, in a loop that keeps checking.</h2>
          <p>Point TestSphere at a URL. It plans and runs browser tests, scans for security issues, proposes fixes and retests them.</p>
        </div>
        <MiniLoop />
        <ul className="auth-points">
          <li><Wand2 size={18} aria-hidden="true" /> Broken selectors are healed automatically, with the old and new locator recorded.</li>
          <li><ShieldCheck size={18} aria-hidden="true" /> Security checks are passive and limited to hosts you allow.</li>
          <li><CheckCircle2 size={18} aria-hidden="true" /> Nothing counts as fixed until a retest passes.</li>
        </ul>
      </aside>
    </div>
  );
}

function GoogleMark() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
      <path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
    </svg>
  );
}

/** Shown instead of the dashboard while sign-in is loading, broken, or needed. */
export function AuthGate() {
  const auth = useAuth();
  if (auth.status === 'loading') {
    return (
      <div className="auth-center">
        <div className="auth-panel">
          <Brand />
          <div className="empty" role="status">Connecting to the backend…</div>
        </div>
      </div>
    );
  }
  if (auth.status === 'offline' || auth.status === 'misconfigured') {
    return (
      <AuthShell>
        <div className="auth-heading">
          <h1>{auth.status === 'offline' ? 'Backend unreachable' : 'Sign-in is not configured'}</h1>
          <p>{auth.status === 'offline' ? 'The dashboard cannot reach its API.' : 'This server has sign-in turned on but is missing its settings.'}</p>
        </div>
        <div className="subbox small cell-wrap">{auth.error}</div>
        {auth.status === 'offline' && <p className="hint m-0">API: <span className="mono">{API_BASE_LABEL}</span></p>}
        <button type="button" className="btn" onClick={auth.retry}><RefreshCw size={16} /> Try again</button>
      </AuthShell>
    );
  }
  return <Login />;
}

/** "Connection check": shows exactly which piece of sign-in is broken. */
function Diagnostics() {
  const { diagnose } = useAuth();
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState(false);
  async function run() {
    setBusy(true);
    try {
      setRows(await diagnose());
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <button type="button" className="link-btn" onClick={run} disabled={busy}>
        <Stethoscope size={14} aria-hidden="true" /> {busy ? 'Checking…' : 'Connection check'}
      </button>
      {rows && (
        <dl className="kv small auth-diag">
          {rows.map(([k, v]) => <React.Fragment key={k}><dt>{k}</dt><dd className="cell-wrap">{v}</dd></React.Fragment>)}
        </dl>
      )}
    </>
  );
}

const HEADINGS = {
  signin: ['Sign in', 'Welcome back. Sign in to your workspace.'],
  signup: ['Create your account', 'Start testing a site in a few minutes.'],
  reset: ['Reset your password', 'We will email you a link to choose a new one.'],
};

function Login() {
  const { signIn, signUp, signInWithGoogle, resetPassword, notice: sessionNotice, clearNotice } = useAuth();
  const [mode, setMode] = useState('signin'); // signin | signup | reset
  const [form, setForm] = useState({ name: '', email: '', password: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  async function attempt(fn) {
    setError(null);
    setNotice(null);
    clearNotice();
    setBusy(true);
    try {
      await fn();
    } catch (err) {
      setError(authMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(e) {
    e.preventDefault();
    if (mode === 'signin') attempt(() => signIn(form.email, form.password));
    else if (mode === 'signup') attempt(() => signUp(form.name, form.email, form.password));
    else {
      attempt(async () => {
        await resetPassword(form.email);
        setNotice(`If an account exists for ${form.email}, a reset link is on its way.`);
      });
    }
  }

  function switchTo(next) {
    setMode(next);
    setError(null);
    setNotice(null);
  }

  const [title, subtitle] = HEADINGS[mode];
  return (
    <AuthShell>
      <div className="auth-heading">
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
      {sessionNotice && <div className="subbox small cell-wrap bad-text" role="alert">{sessionNotice}</div>}

      {mode !== 'reset' && (
        <>
          <button type="button" className="btn btn-block" disabled={busy} onClick={() => attempt(signInWithGoogle)}>
            <GoogleMark /> Continue with Google
          </button>
          <div className="auth-or"><span>or with email</span></div>
        </>
      )}

      <form className="auth-form" onSubmit={onSubmit}>
        {mode === 'signup' && (
          <label className="field">
            Name
            <input className="input" value={form.name} onChange={set('name')} autoComplete="name" maxLength={80} placeholder="Your name" />
          </label>
        )}
        <label className="field">
          Email
          <input className="input" type="email" value={form.email} onChange={set('email')} autoComplete="email" required placeholder="you@company.com" />
        </label>
        {mode !== 'reset' && (
          <label className="field">
            <span className="row-between">
              Password
              {mode === 'signin' && <button type="button" className="link-btn small" onClick={() => switchTo('reset')}>Forgot password?</button>}
            </span>
            <input className="input" type="password" value={form.password} onChange={set('password')} required minLength={mode === 'signup' ? 6 : undefined}
              autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} placeholder={mode === 'signup' ? 'At least 6 characters' : ''} />
          </label>
        )}
        {error && <div className="error-text" role="alert">{error}</div>}
        {notice && <div className="ok-text small" role="status">{notice}</div>}
        <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
          {mode === 'signin' && <><LogIn size={16} /> {busy ? 'Signing in…' : 'Sign in'}</>}
          {mode === 'signup' && <><UserPlus size={16} /> {busy ? 'Creating account…' : 'Create account'}</>}
          {mode === 'reset' && (busy ? 'Sending…' : 'Send reset link')}
        </button>
      </form>

      <p className="small m-0 self-center">
        {mode === 'signin' && <>New to TestSphere? <button type="button" className="link-btn" onClick={() => switchTo('signup')}>Create an account</button></>}
        {mode === 'signup' && <>Already have an account? <button type="button" className="link-btn" onClick={() => switchTo('signin')}>Sign in</button></>}
        {mode === 'reset' && <button type="button" className="link-btn" onClick={() => switchTo('signin')}>Back to sign in</button>}
      </p>

      <div className="auth-foot">
        <Diagnostics />
        <button type="button" className="link-btn" onClick={() => { window.location.hash = '/privacy'; }}>How we handle your data</button>
      </div>
    </AuthShell>
  );
}
