import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render } from '@testing-library/react';

const fb = vi.hoisted(() => ({
  auth: { currentUser: null },
  signInWithPopup: vi.fn(),
  linkWithPopup: vi.fn(),
  linkWithCredential: vi.fn(),
  reauthenticateWithPopup: vi.fn(),
}));

vi.mock('firebase/app', () => ({ initializeApp: () => ({}), getApps: () => [] }));
vi.mock('firebase/auth', () => {
  class GithubAuthProvider {
    addScope() {}
    static credentialFromError(err) { return err.credential || null; }
    static credentialFromResult(res) { return res.credential || null; }
  }
  class GoogleAuthProvider {}
  return {
    GithubAuthProvider, GoogleAuthProvider,
    getAuth: () => fb.auth,
    getRedirectResult: async () => null,
    onAuthStateChanged: () => () => {},
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
  });

  it('connects repositories even when that GitHub login belongs to another account', async () => {
    fb.auth.currentUser = { uid: 'u1', providerData: [{ providerId: 'google.com' }] };
    fb.linkWithPopup.mockRejectedValueOnce(authError('auth/credential-already-in-use', { accessToken: 'gho_repo' }));
    const auth = await renderAuth();

    await expect(auth().githubRepoToken()).resolves.toBe('gho_repo');
  });
});
