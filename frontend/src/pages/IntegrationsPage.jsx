import React from 'react';
import Integrations from '../components/Integrations';
import CodebaseIngestion from '../components/CodebaseIngestion';
import ApiTokens from '../components/ApiTokens';
import { useAuth } from '../state/Auth';

export default function IntegrationsPage() {
  const auth = useAuth();
  return (
    <div className="page">
      <div className="page-title">
        <div>
          <h1>Integrations</h1>
          <p>Connect GitHub and other Git hosts, read a repository into a blueprint, and give coding agents an API token.</p>
        </div>
      </div>
      <div className="grid-main-side">
        <div className="stack-lg">
          <Integrations />
          <CodebaseIngestion />
        </div>
        {auth.mode === 'firebase' && <ApiTokens />}
      </div>
    </div>
  );
}
