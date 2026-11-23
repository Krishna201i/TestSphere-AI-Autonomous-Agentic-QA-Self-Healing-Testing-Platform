import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render } from '@testing-library/react';

const fb = vi.hoisted(() => ({
  auth: { currentUser: null },
  signInWithPopup: vi.fn(),
  linkWithPopup: vi.fn(),
  linkWithCredential: vi.fn(),
  reauthenticateWithPopup: vi.fn(),
  signInAnonymously: vi.fn(),
  signInWithPhoneNumber: vi.fn(),
  onAuthStateChanged: null,
}));

vi.mock('firebase/app', () => ({ initializeApp: () => ({}), getApps: () => [] }));
vi.mock('firebase/auth', () => {
  class GithubAuthProvider {
    addScope() {}
    static credentialFromError(err) { return err.credential || null; }
    static credentialFromResult(res) { return res.credential || null; }
  }
  class GoogleAuthProvider {}
  class RecaptchaVerifier {
    constructor(auth, button, options) { Object.assign(this, { button, options }); }
    clear() {}
  }
  return {
    GithubAuthProvider, GoogleAuthProvider, RecaptchaVerifier,
    getAuth: () => fb.auth,
    getRedirectResult: async () => null,
    onAuthStateChanged: (auth, cb) => { fb.onAuthStateChanged = cb; return () => {}; },
    signInAnonymously: fb.signInAnonymously,
    signInWithPhoneNumber: fb.signInWithPhoneNumber,
    signInWithPopup: fb.signInWithPopup,
    linkWithPopup: fb.linkWithPopup,
    linkWithCredential: fb.linkWithCredential,
    reauthenticateWithPopup: fb.reauthenticateWithPopup,
    createUserWithEmailAndPassword: vi.fn(),
    sendPasswordResetEmail: vi.fn(),
    signInWithEmailAndPassword: vi.fn(),
    signInWithRedirect: vi.fn(),
    signOut: vi.fn(),
    updateProfile: vi.fn(),
  };
});
vi.mock('../services/api', () => ({
  API_BASE_LABEL: 'test',
  configureAuth: () => {},
  getMe: async () => ({}),
  getSystem: async () => ({ auth: { required: true, firebase: { apiKey: 'k', projectId: 'p' } } }),
  probeHealth: async () => ({ ok: true }),
  recordLogin: async () => {},
}));
vi.mock('../state/Workspace', () => ({ clearSavedWorkspaces: () => {} }));

const { AuthProvider, useAuth } = await import('../state/Auth');

function authError(code, credential) {
  return Object.assign(new Error(code), { code, credential });
}

async function renderAuth() {
  let auth;
  function Probe() {
    auth = useAuth();
    return null;
  }
  await act(async () => { render(<AuthProvider><Probe /></AuthProvider>); });
  return () => auth;
}

beforeEach(() => {
  vi.clearAllMocks();
  fb.auth.currentUser = null;
});
afterEach(cleanup);

describe('GitHub on an account that signs in with Google (same email)', () => {
  it('links the refused GitHub sign-in once the user signs in with Google', async () => {
    const githubCred = { providerId: 'github.com', accessToken: 'gho_x' };
    const user = { uid: 'u1', providerData: [{ providerId: 'google.com' }] };
    fb.signInWithPopup
      .mockRejectedValueOnce(authError('auth/account-exists-with-different-credential', githubCred))
      .mockImplementationOnce(async () => { fb.auth.currentUser = user; });
    const auth = await renderAuth();

    await expect(auth().signInWithGitHub()).rejects.toMatchObject({ code: 'auth/account-exists-with-different-credential' });
    await act(() => auth().signInWithGoogle());

    expect(fb.linkWithCredential).toHaveBeenCalledWith(user, githubCred);
    expect(auth().accountNotice).toMatchObject({ ok: true });
    expect(auth().linkNeeded).toBe(false);
  });

  it('asks for the existing sign-in, then says why GitHub could not be linked instead of hiding it', async () => {
    const user = { uid: 'u1', providerData: [{ providerId: 'google.com' }] };
    fb.signInWithPopup
      .mockRejectedValueOnce(authError('auth/account-exists-with-different-credential', { providerId: 'github.com' }))
      .mockImplementationOnce(async () => { fb.auth.currentUser = user; });
    fb.linkWithCredential.mockRejectedValueOnce(authError('auth/credential-already-in-use'));
    const auth = await renderAuth();

    await act(() => auth().signInWithGitHub().catch(() => {}));
    expect(auth().linkNeeded).toBe(true);  // the sign-in screen offers "Continue with Google to add GitHub"
    await act(() => auth().signInWithGoogle());

    expect(auth().accountNotice.ok).toBe(false);
    expect(auth().accountNotice.text).toMatch(/separate TestSphere account/);
  });

  it('connects repositories even when that GitHub login belongs to another account', async () => {
    fb.auth.currentUser = { uid: 'u1', providerData: [{ providerId: 'google.com' }] };
    fb.linkWithPopup.mockRejectedValueOnce(authError('auth/credential-already-in-use', { accessToken: 'gho_repo' }));
    const auth = await renderAuth();

    await expect(auth().githubRepoToken()).resolves.toBe('gho_repo');
  });
});


describe('Phone and guest sign-in', () => {
  it('texts a code, then signs in with it', async () => {
    const confirm = vi.fn(async () => {});
    fb.signInWithPhoneNumber.mockResolvedValueOnce({ confirm });
    const auth = await renderAuth();

    await act(() => auth().sendPhoneCode('+91 98765-43210', 'phone-send'));
    const [, number, verifier] = fb.signInWithPhoneNumber.mock.calls[0];
    expect(number).toBe('+919876543210');
    expect(verifier).toMatchObject({ button: 'phone-send', options: { size: 'invisible' } });

    await act(() => auth().confirmPhoneCode(' 123456 '));
    expect(confirm).toHaveBeenCalledWith('123456');
  });

  it('signs in as a guest, shown as "Guest"', async () => {
    fb.signInAnonymously.mockResolvedValueOnce({});
    const auth = await renderAuth();
    await act(() => auth().signInAsGuest());
    expect(fb.signInAnonymously).toHaveBeenCalled();

    await act(async () => fb.onAuthStateChanged({ uid: 'g1', isAnonymous: true, email: null, displayName: null,
      phoneNumber: null, providerData: [] }));
    expect(auth().user).toMatchObject({ name: 'Guest', provider: 'anonymous' });
    await act(async () => fb.onAuthStateChanged({ uid: 'p1', isAnonymous: false, email: null, displayName: null,
      phoneNumber: '+919876543210', providerData: [{ providerId: 'phone' }] }));
    expect(auth().user).toMatchObject({ name: '+919876543210', provider: 'phone' });
  });
});
