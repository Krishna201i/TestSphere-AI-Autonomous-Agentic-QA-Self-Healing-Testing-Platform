import React, { useCallback, useEffect, useState } from 'react';
import { WorkspaceProvider, useWorkspace } from './state/Workspace';
import { healthStats } from './lib/derive';
import TopNav, { PAGES } from './components/TopNav';
import CommandCenter from './pages/CommandCenter';
import PipelineVisualizer from './pages/PipelineVisualizer';
import AttackerAgent from './pages/AttackerAgent';
import RemediationBridge from './pages/RemediationBridge';
import ValidationEngine from './pages/ValidationEngine';
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
  command: CommandCenter,
  pipeline: PipelineVisualizer,
  attacker: AttackerAgent,
  remediation: RemediationBridge,
  validation: ValidationEngine,
  audit: AuditLogs,
};

function pageFromHash() {
  const id = window.location.hash.replace(/^#\/?/, '');
  return PAGES.some((p) => p.id === id) ? id : 'command';
}

export default function App() {
  const [page, setPage] = useState(pageFromHash);
  const [params, setParams] = useState(null);

  useEffect(() => {
    const onHash = () => setPage(pageFromHash());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  useEffect(() => {
    const label = PAGES.find((p) => p.id === page)?.label;
    document.title = `${label} · TestSphere AI`;
  }, [page]);

  const navigate = useCallback((id, nextParams = null) => {
    setParams(nextParams);
    if (pageFromHash() !== id) window.location.hash = `/${id}`;
    else setPage(id);
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
