import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { WorkspaceProvider, useWorkspace } from './state/Workspace';
import { AuthProvider, useAuth } from './state/Auth';
import { healthStats } from './lib/derive';
import TopNav, { PAGES } from './components/TopNav';
import CommandCenter from './pages/CommandCenter';
import Autopilot from './pages/Autopilot';
import Reports from './pages/Reports';
import Security from './pages/Security';
import Profile from './pages/Profile';
import Privacy, { PrivacyStandalone } from './pages/Privacy';
import { AuthGate } from './pages/Login';
import PipelineVisualizer from './pages/PipelineVisualizer';
import AuditLogs from './pages/AuditLogs';
import RunDetail from './pages/RunDetail';

/** Shown while the API is up but its database is not — explains why actions fail. */
function DatabaseBanner() {
  const { health } = useWorkspace();
  const h = healthStats(health);
  if (!h.dbDown) return null;
  return (
    <div className="alert-banner" role="alert">
      <b>The backend cannot reach its database</b>, so saving and running tests will fail. {h.dbError}
    </div>
  );
}

/** What happened to a GitHub sign-in that had to be linked to an existing account. */
function AccountBanner() {
  const { accountNotice, clearAccountNotice } = useAuth();
  if (!accountNotice) return null;
  return (
    <div className={`alert-banner row-between${accountNotice.ok ? ' ok' : ''}`} role={accountNotice.ok ? 'status' : 'alert'}>
      <span>{accountNotice.text}</span>
      <button type="button" className="btn btn-sm" onClick={clearAccountNotice}>Dismiss</button>
    </div>
  );
}

/** A page that fails to render shows what happened instead of blanking the whole app. */
class PageErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error('Page failed to render', error, info?.componentStack); // eslint-disable-line no-console
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <section className="card" role="alert">
        <div className="card-head"><h3><AlertTriangle size={16} aria-hidden="true" /> This page could not be shown</h3></div>
        <p className="small">{String(this.state.error?.message || this.state.error)}</p>
        <p className="small muted">The rest of the dashboard still works. Try again, or reload the page.</p>
        <button type="button" className="btn btn-sm" onClick={() => this.setState({ error: null })}>Try again</button>
      </section>
    );
  }
}

const VIEWS = {
  home: CommandCenter,
  autopilot: Autopilot,
  reports: Reports,
  security: Security,
  visualizer: PipelineVisualizer,
  audit: AuditLogs,
  profile: Profile,
  privacy: Privacy,
  runs: RunDetail,
};

// Older page ids (links inside cards, bookmarks) → where they live now
const ALIASES = {
  command: { page: 'home' },
  automation: { page: 'autopilot' },
  pipeline: { page: 'visualizer' },
  attacker: { page: 'security', tab: 'attacker' },
  remediation: { page: 'security', tab: 'remediation' },
  validation: { page: 'security', tab: 'validation' },
};

// Reachable by link (profile menu), not shown as a nav pill
const EXTRA_PAGES = [{ id: 'profile', label: 'Profile' }, { id: 'privacy', label: 'Privacy' }, { id: 'runs', label: 'Run' }];
// Pages whose address carries a sub-path: #/security/<tab>, #/runs/<run>[/<execution>]
const SUB_PATH = ['security', 'runs'];

/** "security/remediation" or an old id like "attacker" → { page, tab }. */
function resolve(raw) {
  const [id, ...rest] = (raw || '').split('/');
  const tab = rest.join('/');
  if (ALIASES[id]) return { ...ALIASES[id] };
  if (VIEWS[id]) return { page: id, tab: tab || null };
  return { page: 'home', tab: null };
}

const fromHash = () => resolve(window.location.hash.replace(/^#\/?/, ''));
const hashFor = (page, tab) => `/${page}${tab && SUB_PATH.includes(page) ? `/${tab}` : ''}`;

export default function App() {
  return (
    <AuthProvider>
      <SignedIn />
    </AuthProvider>
  );
}

/** The dashboard only mounts once signed in; it remounts per user so no data leaks across accounts. */
function SignedIn() {
  const auth = useAuth();
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const onHash = () => setHash(window.location.hash);
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  if (auth.status !== 'signedIn') {
    // The privacy notice must be readable before creating an account
    return hash.replace(/^#\/?/, '') === 'privacy' ? <PrivacyStandalone /> : <AuthGate />;
  }
  return <Dashboard key={auth.user.uid} uid={auth.user.uid} />;
}

function Dashboard({ uid }) {
  const initial = fromHash();
  const [page, setPage] = useState(initial.page);
  const [params, setParams] = useState(initial.tab ? { tab: initial.tab } : null);

  useEffect(() => {
    const onHash = () => {
      const r = fromHash();
      setPage(r.page);
      setParams((prev) => (r.tab ? { ...prev, tab: r.tab } : SUB_PATH.includes(r.page) ? null : prev));
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  useEffect(() => {
    const label = [...PAGES, ...EXTRA_PAGES].find((p) => p.id === page)?.label;
    document.title = `${label} · TestSphere AI`;
  }, [page]);

  const pageRef = useRef(page);
  pageRef.current = page;
  const navigate = useCallback((id, nextParams = null) => {
    const r = resolve(id);
    const tab = nextParams?.tab || r.tab || null;
    setParams(tab ? { ...nextParams, tab } : nextParams);
    const samePage = pageRef.current === r.page;
    setPage(r.page);
    const hash = hashFor(r.page, tab);
    if (window.location.hash.replace(/^#/, '') !== hash) window.location.hash = hash;
    if (!samePage) window.scrollTo({ top: 0 }); // e.g. opening a test inside a run keeps your place
  }, []);

  const View = VIEWS[page];
  return (
    <WorkspaceProvider uid={uid}>
      <TopNav page={page} onNavigate={navigate} />
      <DatabaseBanner />
      <AccountBanner />
      <main>
        <PageErrorBoundary key={page}>
          <View onNavigate={navigate} params={params} />
        </PageErrorBoundary>
      </main>
    </WorkspaceProvider>
  );
}
