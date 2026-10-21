import React, { useCallback, useEffect, useState } from 'react';
import { WorkspaceProvider, useWorkspace } from './state/Workspace';
import { AuthProvider, useAuth } from './state/Auth';
import { healthStats } from './lib/derive';
import TopNav, { PAGES } from './components/TopNav';
import CommandCenter from './pages/CommandCenter';
import Autopilot from './pages/Autopilot';
import Reports from './pages/Reports';
import Security from './pages/Security';
import Profile from './pages/Profile';
import { AuthGate } from './pages/Login';
import PipelineVisualizer from './pages/PipelineVisualizer';
import AuditLogs from './pages/AuditLogs';

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

const VIEWS = {
  home: CommandCenter,
  autopilot: Autopilot,
  reports: Reports,
  security: Security,
  visualizer: PipelineVisualizer,
  audit: AuditLogs,
  profile: Profile,
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
const EXTRA_PAGES = [{ id: 'profile', label: 'Profile' }];

/** "security/remediation" or an old id like "attacker" → { page, tab }. */
function resolve(raw) {
  const [id, tab] = (raw || '').split('/');
  if (ALIASES[id]) return { ...ALIASES[id] };
  if (VIEWS[id]) return { page: id, tab: tab || null };
  return { page: 'home', tab: null };
}

const fromHash = () => resolve(window.location.hash.replace(/^#\/?/, ''));
const hashFor = (page, tab) => `/${page}${tab && page === 'security' ? `/${tab}` : ''}`;

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
  if (auth.status !== 'signedIn') return <AuthGate />;
  return <Dashboard key={auth.user.uid} />;
}

function Dashboard() {
  const initial = fromHash();
  const [page, setPage] = useState(initial.page);
  const [params, setParams] = useState(initial.tab ? { tab: initial.tab } : null);

  useEffect(() => {
    const onHash = () => {
      const r = fromHash();
      setPage(r.page);
      setParams((prev) => (r.tab ? { ...prev, tab: r.tab } : prev));
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  useEffect(() => {
    const label = [...PAGES, ...EXTRA_PAGES].find((p) => p.id === page)?.label;
    document.title = `${label} · TestSphere AI`;
  }, [page]);

  const navigate = useCallback((id, nextParams = null) => {
    const r = resolve(id);
    const tab = nextParams?.tab || r.tab || null;
    setParams(tab ? { ...nextParams, tab } : nextParams);
    setPage(r.page);
    const hash = hashFor(r.page, tab);
    if (window.location.hash.replace(/^#/, '') !== hash) window.location.hash = hash;
    window.scrollTo({ top: 0 });
  }, []);

  const View = VIEWS[page];
  return (
    <WorkspaceProvider>
      <TopNav page={page} onNavigate={navigate} />
      <DatabaseBanner />
      <main>
        <View onNavigate={navigate} params={params} />
      </main>
    </WorkspaceProvider>
  );
}
