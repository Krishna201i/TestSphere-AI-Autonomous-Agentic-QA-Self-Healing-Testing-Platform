import React, { useState } from 'react';
import { LogIn, RefreshCw, UserPlus } from 'lucide-react';
import { authMessage, useAuth } from '../state/Auth';
import { Logo } from '../components/TopNav';
import { API_BASE_LABEL } from '../services/api';

function AuthShell({ children }) {
  return (
    <div className="auth-screen">
      <div className="auth-card card">
        <div className="auth-brand">
          <Logo size={44} />
          <div>
            <div className="brand-name">TESTSPHERE AI</div>
            <div className="small muted">Autonomous QA &amp; self-healing testing</div>
          </div>
        </div>
        {children}
      </div>
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
    return <AuthShell><div className="empty">Connecting to the backend…</div></AuthShell>;
  }
  if (auth.status === 'offline' || auth.status === 'misconfigured') {
    return (
      <AuthShell>
        <h2 className="auth-title">{auth.status === 'offline' ? 'Backend unreachable' : 'Sign-in is not configured'}</h2>
        <div className="subbox small cell-wrap">{auth.error}</div>
        {auth.status === 'offline' && <p className="hint" style={{ margin: 0 }}>API: <span className="mono">{API_BASE_LABEL}</span></p>}
        <button type="button" className="btn" onClick={auth.retry}><RefreshCw size={16} /> Try again</button>
      </AuthShell>
    );
  }
  return <Login />;
}

function Login() {
  const { signIn, signUp, signInWithGoogle, resetPassword } = useAuth();
  const [mode, setMode] = useState('signin'); // signin | signup | reset
  const [form, setForm] = useState({ name: '', email: '', password: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  async function attempt(fn) {
    setError(null);
    setNotice(null);
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

  return (
    <AuthShell>
      {mode !== 'reset' && (
        <div className="tabs auth-tabs" role="tablist" aria-label="Sign in or create an account">
          <button type="button" role="tab" aria-selected={mode === 'signin'} className={`tab ${mode === 'signin' ? 'active' : ''}`} onClick={() => switchTo('signin')}>Sign in</button>
          <button type="button" role="tab" aria-selected={mode === 'signup'} className={`tab ${mode === 'signup' ? 'active' : ''}`} onClick={() => switchTo('signup')}>Create account</button>
        </div>
      )}
      {mode === 'reset' && <h2 className="auth-title">Reset your password</h2>}

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
            Password
            <input className="input" type="password" value={form.password} onChange={set('password')} required minLength={mode === 'signup' ? 6 : undefined}
              autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} placeholder={mode === 'signup' ? 'At least 6 characters' : ''} />
          </label>
        )}
        {error && <div className="error-text" role="alert">{error}</div>}
        {notice && <div className="ok-text small" role="status">{notice}</div>}
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {mode === 'signin' && <><LogIn size={16} /> {busy ? 'Signing in…' : 'Sign in'}</>}
          {mode === 'signup' && <><UserPlus size={16} /> {busy ? 'Creating account…' : 'Create account'}</>}
          {mode === 'reset' && (busy ? 'Sending…' : 'Send reset link')}
        </button>
      </form>

      {mode !== 'reset' ? (
        <>
          <div className="auth-or"><span>or</span></div>
          <button type="button" className="btn" disabled={busy} onClick={() => attempt(signInWithGoogle)}>
            <GoogleMark /> Continue with Google
          </button>
          {mode === 'signin' && (
            <button type="button" className="link-btn" onClick={() => switchTo('reset')}>Forgot your password?</button>
          )}
        </>
      ) : (
        <button type="button" className="link-btn" onClick={() => switchTo('signin')}>Back to sign in</button>
      )}
    </AuthShell>
  );
}
