import React, { useState } from 'react';
import {
  ArrowRight, Bandage, Eye, EyeOff, Github, Lock, Mail, Phone, RefreshCw, Rocket, ShieldCheck, Stethoscope, User, UserPlus, Zap,
} from 'lucide-react';
import { authMessage, useAuth } from '../state/Auth';
import { Logo } from '../components/TopNav';
import { API_BASE_LABEL } from '../services/api';

function Brand({ tagline = false }) {
  return (
    <div className="auth-brand">
      <Logo size={tagline ? 44 : 32} />
      <span className="auth-brand-text">
        <span className="brand-name">TestSphere <b>AI</b></span>
        {tagline && <span className="auth-brand-tag">Autonomous QA Platform</span>}
      </span>
    </div>
  );
}

const FEATURES = [
  [Zap, 'AI Test Generation', 'Turn goals into tests'],
  [Bandage, 'Self-Healing', 'Auto-fix broken locators'],
  [ShieldCheck, 'Security Scanning', 'Detect and prioritise risks'],
  [Rocket, 'Auto Fix & Deploy', 'Pull requests, verified releases'],
];

// Measured results (README "Results"), not live usage figures
const STATS = [
  ['95.7%', 'Self-healing success'],
  ['0', 'False heals'],
  ['18 / 19', 'Bugs caught from plain English'],
  ['2,000+', 'Automated tests in CI'],
];

/** Decorative dotted wave along the bottom of the product panel. */
function Wave() {
  return (
    <svg className="auth-wave" viewBox="0 0 600 160" preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <pattern id="auth-dots" width="8" height="8" patternUnits="userSpaceOnUse">
          <circle cx="2" cy="2" r="1.1" className="auth-wave-dot" />
        </pattern>
        <linearGradient id="auth-wave-fade" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="white" stopOpacity="1" />
          <stop offset="1" stopColor="white" stopOpacity="0.15" />
        </linearGradient>
        <mask id="auth-wave-mask"><rect width="600" height="160" fill="url(#auth-wave-fade)" /></mask>
      </defs>
      <path className="auth-wave-line" d="M0 70 C 120 20, 230 120, 360 70 S 540 30, 600 60" />
      <path d="M0 80 C 120 30, 230 130, 360 80 S 540 40, 600 70 L 600 160 L 0 160 Z" fill="url(#auth-dots)" mask="url(#auth-wave-mask)" />
    </svg>
  );
}

function AuthShell({ children, top = null }) {
  return (
    <div className="auth-screen">
      <aside className="auth-aside" aria-label="About TestSphere AI">
        <Brand tagline />
        <div className="auth-hero">
          <p className="auth-eyebrow">Autonomous QA &amp; testing</p>
          <h2>Test, Heal, Secure &amp; Deploy — <em>Autonomously.</em></h2>
          <p>An AI-native QA platform that tests your application end to end, self-heals failures, finds vulnerabilities and ships verified fixes.</p>
        </div>
        <ul className="auth-features">
          {FEATURES.map(([Icon, title, text]) => (
            <li key={title}>
              <span className="auth-feature-icon"><Icon size={20} aria-hidden="true" /></span>
              <span><b>{title}</b><span>{text}</span></span>
            </li>
          ))}
        </ul>
        <dl className="auth-stats">
          {STATS.map(([value, label]) => (
            <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
          ))}
        </dl>
        <Wave />
      </aside>
      <main className="auth-main">
        {top && <div className="auth-top">{top}</div>}
        <div className="auth-mobile-brand"><Brand /></div>
        <div className="auth-card">
          {children}
        </div>
      </main>
    </div>
  );
}

function MicrosoftMark() {
  return (
    <svg width="18" height="18" viewBox="0 0 23 23" aria-hidden="true">
      <path fill="#F25022" d="M1 1h10v10H1z" />
      <path fill="#7FBA00" d="M12 1h10v10H12z" />
      <path fill="#00A4EF" d="M1 12h10v10H1z" />
      <path fill="#FFB900" d="M12 12h10v10H12z" />
    </svg>
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
        <div className="auth-card">
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
  signin: ['Welcome back', 'Sign in to your TestSphere AI workspace'],
  signup: ['Create your account', 'Start testing a site in a few minutes'],
  reset: ['Reset your password', 'We will email you a link to choose a new one'],
  phone: ['Sign in with your phone', 'We will text you a 6-digit code'],
};

function Login() {
  const {
    signIn, signUp, signInWithGoogle, signInWithGitHub, signInWithMicrosoft, resetPassword, signInAsGuest, sendPhoneCode,
    confirmPhoneCode,
    linkNeeded, notice: sessionNotice, clearNotice,
  } = useAuth();
  const [mode, setMode] = useState('signin'); // signin | signup | reset | phone
  const [form, setForm] = useState({ name: '', email: '', password: '', phone: '', code: '' });
  const [codeSent, setCodeSent] = useState(false);
  const [remember, setRemember] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
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

  function onPhoneSubmit(e) {
    e.preventDefault();
    if (codeSent) {
      attempt(() => confirmPhoneCode(form.code));
    } else {
      attempt(async () => {
        await sendPhoneCode(form.phone, 'phone-send');
        setCodeSent(true);
        setNotice(`Code sent to ${form.phone}.`);
      });
    }
  }

  function onSubmit(e) {
    e.preventDefault();
    if (mode === 'signin') attempt(() => signIn(form.email, form.password, remember));
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
    setCodeSent(false);
  }

  const [title, subtitle] = HEADINGS[mode];
  const top = mode === 'signup'
    ? <>Have an account? <button type="button" className="btn btn-sm auth-top-btn" onClick={() => switchTo('signin')}>Sign in</button></>
    : <>New here? <button type="button" className="btn btn-sm auth-top-btn" onClick={() => switchTo('signup')}>Create account</button></>;
  return (
    <AuthShell top={top}>
      <div className="auth-heading">
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
      {sessionNotice && <div className="subbox small cell-wrap bad-text" role="alert">{sessionNotice}</div>}

      {linkNeeded && (
        <div className="subbox small cell-wrap" role="status">
          <b>This email already has a TestSphere account.</b> Sign in the way you first did (usually Google) and GitHub
          is added to it, so either works from then on.
          <button type="button" className="btn btn-primary btn-block mt-2" disabled={busy} onClick={() => attempt(signInWithGoogle)}>
            <GoogleMark /> Continue with Google to add GitHub
          </button>
        </div>
      )}

      {(mode === 'signin' || mode === 'signup') && (
        <>
          <div className="auth-providers">
            <button type="button" className="btn auth-provider" aria-label="Continue with Google" disabled={busy}
              onClick={() => attempt(signInWithGoogle)}>
              <GoogleMark /> Google
            </button>
            <button type="button" className="btn auth-provider" aria-label="Continue with GitHub" disabled={busy}
              onClick={() => attempt(signInWithGitHub)}>
              <Github size={18} aria-hidden="true" /> GitHub
            </button>
            <button type="button" className="btn auth-provider" aria-label="Continue with Microsoft" disabled={busy}
              onClick={() => attempt(signInWithMicrosoft)}>
              <MicrosoftMark /> Microsoft
            </button>
          </div>
          <button type="button" className="btn btn-block auth-provider" disabled={busy} onClick={() => switchTo('phone')}>
            <Phone size={18} aria-hidden="true" /> Continue with phone
          </button>
          <div className="auth-or"><span>{mode === 'signup' ? 'or sign up with email' : 'or sign in with email'}</span></div>
        </>
      )}

      {mode === 'phone' && (
        <form className="auth-form" onSubmit={onPhoneSubmit}>
          <label className="field">
            Phone number
            <span className="auth-input">
              <Phone size={18} aria-hidden="true" />
              <input className="input" type="tel" value={form.phone} onChange={set('phone')} autoComplete="tel" required
                placeholder="+91 98765 43210" disabled={codeSent} />
            </span>
          </label>
          {codeSent && (
            <label className="field">
              Code from the SMS
              <input className="input" inputMode="numeric" value={form.code} onChange={set('code')} required
                autoComplete="one-time-code" maxLength={6} placeholder="123456" />
            </label>
          )}
          {error && <div className="error-text" role="alert">{error}</div>}
          {notice && <div className="ok-text small" role="status">{notice}</div>}
          <button type="submit" id="phone-send" className="btn btn-primary btn-block auth-submit" disabled={busy}>
            {codeSent ? (busy ? 'Checking…' : 'Sign in') : (busy ? 'Sending…' : 'Send code')}
          </button>
          {codeSent && <button type="button" className="link-btn small" onClick={() => switchTo('phone')}>Use another number</button>}
        </form>
      )}

      {mode !== 'phone' && (
      <form className="auth-form" onSubmit={onSubmit}>
        {mode === 'signup' && (
          <label className="field">
            <span className="sr-only">Name</span>
            <span className="auth-input">
              <User size={18} aria-hidden="true" />
              <input className="input" value={form.name} onChange={set('name')} autoComplete="name" maxLength={80} placeholder="Your name" />
            </span>
          </label>
        )}
        <label className="field">
          <span className="sr-only">Email</span>
          <span className="auth-input">
            <Mail size={18} aria-hidden="true" />
            <input className="input" type="email" value={form.email} onChange={set('email')} autoComplete="email" required
              placeholder="Enter your email" />
          </span>
        </label>
        {mode !== 'reset' && (
          <label className="field">
            <span className="sr-only">Password</span>
            <span className="auth-input">
              <Lock size={18} aria-hidden="true" />
              <input className="input" type={showPassword ? 'text' : 'password'} value={form.password} onChange={set('password')} required
                minLength={mode === 'signup' ? 6 : undefined} autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
                placeholder={mode === 'signup' ? 'Choose a password (6+ characters)' : 'Enter your password'} />
              <button type="button" className="auth-reveal" onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? 'Hide password' : 'Show password'} aria-pressed={showPassword}>
                {showPassword ? <EyeOff size={18} aria-hidden="true" /> : <Eye size={18} aria-hidden="true" />}
              </button>
            </span>
          </label>
        )}
        {mode === 'signin' && (
          <div className="row-between">
            <label className="auth-check">
              <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> Remember me
            </label>
            <button type="button" className="link-btn small" onClick={() => switchTo('reset')}>Forgot password?</button>
          </div>
        )}
        {error && <div className="error-text" role="alert">{error}</div>}
        {notice && <div className="ok-text small" role="status">{notice}</div>}
        <button type="submit" className="btn btn-primary btn-block auth-submit" disabled={busy}>
          {mode === 'signin' && <>{busy ? 'Signing in…' : 'Sign in'} <ArrowRight size={18} aria-hidden="true" /></>}
          {mode === 'signup' && <><UserPlus size={16} aria-hidden="true" /> {busy ? 'Creating account…' : 'Create account'}</>}
          {mode === 'reset' && (busy ? 'Sending…' : 'Send reset link')}
        </button>
      </form>
      )}

      {(mode === 'reset' || mode === 'phone') && (
        <button type="button" className="link-btn small self-center" onClick={() => switchTo('signin')}>Back to sign in</button>
      )}
      {mode === 'signin' && (
        <p className="hint m-0 self-center">
          <button type="button" className="link-btn" disabled={busy} onClick={() => attempt(signInAsGuest)}>
            <User size={14} aria-hidden="true" /> Try it as a guest
          </button>{' '}
          (no account; your work is lost when you sign out)
        </p>
      )}

      <p className="auth-legal">
        By continuing, you agree to{' '}
        <button type="button" className="link-btn" onClick={() => { window.location.hash = '/privacy'; }}>how we handle your data</button>.
      </p>
      <div className="auth-foot"><Diagnostics /></div>
    </AuthShell>
  );
}
