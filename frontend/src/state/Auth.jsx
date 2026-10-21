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
  GoogleAuthProvider,
  createUserWithEmailAndPassword,
  getAuth,
  onAuthStateChanged,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut as firebaseSignOut,
  updateProfile,
} from 'firebase/auth';
import { configureAuth, getSystem, recordLogin } from '../services/api';

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
  'auth/popup-closed-by-user': 'The Google window was closed before signing in.',
  'auth/cancelled-popup-request': 'The Google window was closed before signing in.',
  'auth/popup-blocked': 'The browser blocked the Google window. Allow pop-ups for this site and try again.',
  'auth/too-many-requests': 'Too many attempts. Wait a minute, or reset your password.',
  'auth/network-request-failed': 'Cannot reach Firebase. Check your internet connection.',
  'auth/operation-not-allowed':
    'This sign-in method is turned off. Enable it in Firebase console → Authentication → Sign-in method.',
  'auth/configuration-not-found':
    'Authentication is not set up for this Firebase project. Open Firebase console → Authentication → Get started.',
  'auth/unauthorized-domain':
    'This site\'s domain is not authorized. Add it in Firebase console → Authentication → Settings → Authorized domains.',
  'auth/invalid-api-key': 'The server\'s FIREBASE_WEB_API_KEY is wrong. Copy it from Firebase console → Project settings.',
  'auth/api-key-not-valid.-please-pass-a-valid-api-key.':
    'The server\'s FIREBASE_WEB_API_KEY is wrong. Copy it from Firebase console → Project settings.',
};

export function authMessage(err) {
  return FIREBASE_ERRORS[err?.code] || err?.message?.replace(/^Firebase: /, '') || 'Sign-in failed.';
}

function toUser(u) {
  return {
    uid: u.uid,
    email: u.email,
    name: u.displayName,
    photo: u.photoURL,
    provider: u.providerData?.[0]?.providerId || 'password',
  };
}

export function AuthProvider({ children }) {
  const [state, setState] = useState({ status: 'loading', mode: null, user: null, error: null });
  const authRef = useRef(null);

  const start = useCallback(async () => {
    setState({ status: 'loading', mode: null, user: null, error: null });
    let system;
    try {
      system = await getSystem();
    } catch (err) {
      setState({ status: 'offline', mode: null, user: null, error: err.message });
      return;
    }
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
      unauthorized: () => firebaseSignOut(fbAuth),
    });
    onAuthStateChanged(fbAuth, (u) => {
      setState({ status: u ? 'signedIn' : 'signedOut', mode: 'firebase', user: u ? toUser(u) : null, error: null });
    });
  }, []);

  useEffect(() => { start(); }, [start]);

  const signIn = useCallback(async (email, password) => {
    await signInWithEmailAndPassword(authRef.current, email.trim(), password);
    recordLogin().catch(() => {});
  }, []);

  const signUp = useCallback(async (name, email, password) => {
    const cred = await createUserWithEmailAndPassword(authRef.current, email.trim(), password);
    if (name.trim()) {
      await updateProfile(cred.user, { displayName: name.trim() });
      await cred.user.getIdToken(true); // so the token carries the name
      setState((s) => ({ ...s, user: toUser(cred.user) }));
    }
    recordLogin().catch(() => {});
  }, []);

  const signInWithGoogle = useCallback(async () => {
    await signInWithPopup(authRef.current, new GoogleAuthProvider());
    recordLogin().catch(() => {});
  }, []);

  const resetPassword = useCallback((email) => sendPasswordResetEmail(authRef.current, email.trim()), []);

  const signOut = useCallback(async () => {
    if (authRef.current) await firebaseSignOut(authRef.current);
  }, []);

  const value = useMemo(() => ({
    ...state, retry: start, signIn, signUp, signInWithGoogle, resetPassword, signOut,
  }), [state, start, signIn, signUp, signInWithGoogle, resetPassword, signOut]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}
