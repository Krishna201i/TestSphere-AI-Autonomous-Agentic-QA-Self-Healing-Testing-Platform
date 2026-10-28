/**
 * Sign-in state for the dashboard (Firebase Authentication).
 *
 * The backend says whether sign-in is required and hands over the public
 * Firebase web config via /api/system, so the same build works against a
 * local backend (sign-in off, single local user) and production.
 *
 * status: loading | offline | misconfigured | signedOut | signedIn
 */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { initializeApp, getApps } from 'firebase/app';
import {
  GithubAuthProvider,
  GoogleAuthProvider,
  RecaptchaVerifier,
  createUserWithEmailAndPassword,
  getAuth,
  getRedirectResult,
  linkWithCredential,
  linkWithPopup,
  onAuthStateChanged,
  reauthenticateWithPopup,
  sendPasswordResetEmail,
  signInAnonymously,
  signInWithEmailAndPassword,
  signInWithPhoneNumber,
  signInWithPopup,
  signInWithRedirect,
  signOut as firebaseSignOut,
  updateProfile,
} from 'firebase/auth';
import { API_BASE_LABEL, configureAuth, getMe, getSystem, probeHealth, recordLogin } from '../services/api';
import { clearSavedWorkspaces } from './Workspace';

const AuthContext = createContext(null);

const LOCAL_USER = { uid: 'local-dev', email: null, name: 'Local developer', photo: null, provider: 'local' };

const FIREBASE_ERRORS = {
  'auth/invalid-credential': 'Wrong email or password.',
  'auth/invalid-login-credentials': 'Wrong email or password.',
  'auth/wrong-password': 'Wrong email or password.',
  'auth/user-not-found': 'No account with this email. Create one instead.',
  'auth/email-already-in-use': 'An account with this email already exists. Sign in instead.',
  'auth/weak-password': 'Use a password of at least 6 characters.',
  'auth/invalid-email': 'That email address is not valid.',
  'auth/missing-password': 'Enter your password.',
  'auth/popup-closed-by-user': 'The sign-in window was closed before finishing.',
  'auth/cancelled-popup-request': 'The sign-in window was closed before finishing.',
  'auth/popup-blocked': 'The browser blocked the sign-in window. Allow pop-ups for this site and try again.',
  'auth/operation-not-supported-in-this-environment':
    'This browser cannot open the sign-in window here (e.g. an in-app browser). Open the site in Chrome, Safari or Firefox, or sign in with email.',
  'auth/web-storage-unsupported':
    'This browser blocks the storage sign-in needs (private mode or blocked site data). Allow site data, or sign in with email.',
  'auth/account-exists-with-different-credential':
    'This email already has a TestSphere account. Sign in once the way you first did (Google or email) and '
    + 'GitHub will be linked to it, so either works from then on.',
  'auth/credential-already-in-use':
    'This GitHub login already belongs to a separate TestSphere account (made by signing in with GitHub before). '
    + 'To merge them: sign in with GitHub, delete that account in Profile, then sign in with Google and connect GitHub.',
  'auth/invalid-phone-number': 'Enter the phone number with its country code, e.g. +91 98765 43210.',
  'auth/missing-phone-number': 'Enter your phone number.',
  'auth/invalid-verification-code': 'That code is not right. Check the SMS and try again.',
  'auth/code-expired': 'The code expired. Send a new one.',
  'auth/quota-exceeded': 'The SMS limit for this project is reached. Try again later or sign in another way.',
  'auth/captcha-check-failed': 'The robot check failed. Reload the page and try again.',
  'auth/admin-restricted-operation': 'This sign-in method is turned off for this project.',
  'auth/user-mismatch': 'That is a different GitHub account from the one linked here. Pick the linked account in the GitHub window.',
  'auth/too-many-requests': 'Too many attempts. Wait a minute, or reset your password.',
  'auth/network-request-failed': 'Cannot reach Firebase. Check your internet connection.',
  'auth/operation-not-allowed':
    'This sign-in method is turned off. Enable it in Firebase console → Authentication → Sign-in method.',
  'auth/configuration-not-found':
    'Authentication is not set up for this Firebase project. Open Firebase console → Authentication → Get started.',
  'auth/unauthorized-domain': () =>
    `This site's domain (${window.location.hostname}) is not authorized for sign-in. Add it in Firebase console → `
    + 'Authentication → Settings → Authorized domains. Vercel preview links change on every deploy, so use your '
    + 'production domain.',
  'auth/invalid-api-key': 'The server\'s FIREBASE_WEB_API_KEY is wrong. Copy it from Firebase console → Project settings.',
  'auth/api-key-not-valid.-please-pass-a-valid-api-key.':
    'The server\'s FIREBASE_WEB_API_KEY is wrong. Copy it from Firebase console → Project settings.',
};

// Popup sign-in cannot work here; fall back to a full-page redirect
const NEEDS_REDIRECT = ['auth/popup-blocked', 'auth/operation-not-supported-in-this-environment', 'auth/web-storage-unsupported'];

export function authMessage(err) {
  const known = FIREBASE_ERRORS[err?.code];
  if (typeof known === 'function') return known();
  return known || err?.message?.replace(/^Firebase: /, '') || 'Sign-in failed.';
}

function toUser(u) {
  return {
    uid: u.uid,
    email: u.email,
    // Phone and guest accounts have no name or email: show something readable
    name: u.displayName || (u.email ? null : u.phoneNumber || (u.isAnonymous ? 'Guest' : null)),
    photo: u.photoURL,
    provider: u.isAnonymous ? 'anonymous' : u.providerData?.[0]?.providerId || 'password',
  };
}

export function AuthProvider({ children }) {
  const [state, setState] = useState({ status: 'loading', mode: null, user: null, error: null });
  // Why the last session ended (shown on the login page instead of a silent bounce)
  const [notice, setNotice] = useState(null);
  const authRef = useRef(null);
  const systemRef = useRef(null);
  // A GitHub sign-in refused because the email already has an account (one
  // account per email): linked to that account once the user signs in to it
  const pendingGitHubRef = useRef(null);
  // True while such a GitHub sign-in waits for the existing account's sign-in
  const [linkNeeded, setLinkNeeded] = useState(false);
  // What happened to that link, shown in the dashboard after signing in
  const [accountNotice, setAccountNotice] = useState(null);
  const phoneRef = useRef(null); // the SMS confirmation in progress

  const rememberPendingGitHub = useCallback((err) => {
    if (err?.code !== 'auth/account-exists-with-different-credential') return;
    pendingGitHubRef.current = GithubAuthProvider.credentialFromError(err);
    setLinkNeeded(Boolean(pendingGitHubRef.current));
  }, []);

  const linkPendingGitHub = useCallback(async () => {
    const pending = pendingGitHubRef.current;
    const user = authRef.current?.currentUser;
    if (!pending || !user) return;
    pendingGitHubRef.current = null;
    setLinkNeeded(false);
    try {
      await linkWithCredential(user, pending);
      setAccountNotice({ ok: true, text: 'GitHub is now linked: you can sign in with Google or GitHub.' });
    } catch (err) {
      // Signing in itself worked; say why GitHub is not linked instead of hiding it
      if (err?.code !== 'auth/provider-already-linked') {
        setAccountNotice({ ok: false, text: `GitHub could not be linked to this account. ${authMessage(err)}` });
      }
    }
  }, []);

  const start = useCallback(async () => {
    setState({ status: 'loading', mode: null, user: null, error: null });
    let system;
    try {
      system = await getSystem();
    } catch (err) {
      setState({ status: 'offline', mode: null, user: null, error: err.message });
      return;
    }
    systemRef.current = system;
    const auth = system.auth;
    if (!auth?.required) {
      configureAuth({});
      setState({ status: 'signedIn', mode: 'local', user: LOCAL_USER, error: null });
      return;
    }
    if (!auth.firebase?.apiKey || !auth.firebase?.projectId) {
      setState({
        status: 'misconfigured', mode: 'firebase', user: null,
        error: 'This server requires sign-in, but its Firebase web config is incomplete. Set FIREBASE_WEB_API_KEY '
          + '(Firebase console → Project settings → General → Your apps → Web app) on the backend and restart it.',
      });
      return;
    }
    const app = getApps()[0] || initializeApp(auth.firebase);
    const fbAuth = getAuth(app);
    authRef.current = fbAuth;
    configureAuth({
      getToken: async () => (fbAuth.currentUser ? fbAuth.currentUser.getIdToken() : null),
      unauthorized: (detail) => {
        setNotice(`Firebase signed you in, but the backend rejected the session: ${detail}`);
        firebaseSignOut(fbAuth);
      },
    });
    getRedirectResult(fbAuth).then((res) => { if (res) recordLogin().catch(() => {}); })
      .catch((err) => {
        rememberPendingGitHub(err);
        setNotice(authMessage(err));
      });
    onAuthStateChanged(fbAuth, (u) => {
      setState({ status: u ? 'signedIn' : 'signedOut', mode: 'firebase', user: u ? toUser(u) : null, error: null });
    });
  }, [rememberPendingGitHub]);

  useEffect(() => { start(); }, [start]);

  const signIn = useCallback(async (email, password) => {
    await signInWithEmailAndPassword(authRef.current, email.trim(), password);
    await linkPendingGitHub();
    recordLogin().catch(() => {});
  }, [linkPendingGitHub]);

  const signUp = useCallback(async (name, email, password) => {
    const cred = await createUserWithEmailAndPassword(authRef.current, email.trim(), password);
    if (name.trim()) {
      await updateProfile(cred.user, { displayName: name.trim() });
      await cred.user.getIdToken(true); // so the token carries the name
      setState((s) => ({ ...s, user: toUser(cred.user) }));
    }
    recordLogin().catch(() => {});
  }, []);

  const signInWithProvider = useCallback(async (makeProvider) => {
    try {
      await signInWithPopup(authRef.current, makeProvider());
    } catch (err) {
      rememberPendingGitHub(err);
      if (!NEEDS_REDIRECT.includes(err?.code)) throw err;
      // A redirect only comes back signed in when Firebase's auth domain is this
      // site's own (browsers partition the storage it needs across domains);
      // elsewhere it would silently return to the login page, so say what to do
      if (systemRef.current?.auth?.firebase?.authDomain !== window.location.host) throw err;
      await signInWithRedirect(authRef.current, makeProvider());
      return;
    }
    await linkPendingGitHub();
    recordLogin().catch(() => {});
  }, [rememberPendingGitHub, linkPendingGitHub]);
  const signInWithGoogle = useCallback(() => signInWithProvider(() => new GoogleAuthProvider()), [signInWithProvider]);
  // Identity only: repository access is asked for separately (githubRepoToken)
  const signInWithGitHub = useCallback(() => signInWithProvider(() => new GithubAuthProvider()), [signInWithProvider]);

  /**
   * A GitHub token with repository access, from a GitHub window: links GitHub to
   * this account, or re-confirms it when the account already signs in with GitHub.
   * Null when sign-in is off (local mode: paste a token instead).
   */
  const githubRepoToken = useCallback(async () => {
    const user = authRef.current?.currentUser;
    if (!user) return null;
    const provider = new GithubAuthProvider();
    provider.addScope('repo');
    const linked = user.providerData.some((p) => p.providerId === 'github.com');
    try {
      const result = linked ? await reauthenticateWithPopup(user, provider) : await linkWithPopup(user, provider);
      return GithubAuthProvider.credentialFromResult(result)?.accessToken || null;
    } catch (err) {
      // The GitHub login already belongs to another TestSphere account (e.g. one
      // made by signing in with GitHub before): it can't be linked, but GitHub
      // still granted repository access, which is all connecting needs
      const token = err?.code === 'auth/credential-already-in-use'
        ? GithubAuthProvider.credentialFromError(err)?.accessToken : null;
      if (token) return token;
      throw err;
    }
  }, []);

  /** Everything needed to tell why sign-in fails, checked live. */
  const diagnose = useCallback(async () => {
    const health = await probeHealth();
    const auth = systemRef.current?.auth;
    let session = 'not signed in';
    if (authRef.current?.currentUser) {
      try {
        await getMe();
        session = 'accepted by the backend';
      } catch (err) {
        session = `rejected: ${err.message}`;
      }
    }
    return [
      ['This site', window.location.origin],
      ['Backend', `${API_BASE_LABEL} — ${health.ok ? `reachable (${health.ms} ms)` : 'unreachable'}`],
      ['Database', health.ok ? (health.db === 'ok' ? 'connected' : health.dbError || health.db) : '—'],
      ['Sign-in required', auth ? String(auth.required) : 'unknown'],
      ['Firebase project', auth?.firebase?.projectId || '—'],
      ['Web API key on server', auth?.firebase?.apiKey ? 'set' : 'missing'],
      ['Current session', session],
    ];
  }, []);

  const resetPassword = useCallback((email) => sendPasswordResetEmail(authRef.current, email.trim()), []);

  /** A guest account: no email or password; its data stays with this browser's session. */
  const signInAsGuest = useCallback(async () => {
    await signInAnonymously(authRef.current);
    recordLogin().catch(() => {});
  }, []);

  /** Text an SMS code to *phone* (with country code); the invisible robot check sits on *buttonId*. */
  const sendPhoneCode = useCallback(async (phone, buttonId) => {
    const verifier = new RecaptchaVerifier(authRef.current, buttonId, { size: 'invisible' });
    try {
      phoneRef.current = await signInWithPhoneNumber(authRef.current, phone.replace(/[\s()-]/g, ''), verifier);
    } catch (err) {
      verifier.clear();
      throw err;
    }
  }, []);

  const confirmPhoneCode = useCallback(async (code) => {
    if (!phoneRef.current) throw Object.assign(new Error('Send a code first.'), { code: 'auth/code-expired' });
    await phoneRef.current.confirm(code.trim());
    phoneRef.current = null;
    await linkPendingGitHub();
    recordLogin().catch(() => {});
  }, [linkPendingGitHub]);

  const signOut = useCallback(async () => {
    clearSavedWorkspaces(); // the next person on this browser starts clean
    if (authRef.current) await firebaseSignOut(authRef.current);
  }, []);

  const value = useMemo(() => ({
    ...state, notice, clearNotice: () => setNotice(null), diagnose, linkNeeded,
    accountNotice, clearAccountNotice: () => setAccountNotice(null),
    retry: start, signIn, signUp, signInWithGoogle, signInWithGitHub, githubRepoToken, resetPassword, signOut,
    signInAsGuest, sendPhoneCode, confirmPhoneCode,
  }), [state, notice, diagnose, linkNeeded, accountNotice, start, signIn, signUp, signInWithGoogle, signInWithGitHub,
    githubRepoToken, resetPassword, signOut, signInAsGuest, sendPhoneCode, confirmPhoneCode]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}
