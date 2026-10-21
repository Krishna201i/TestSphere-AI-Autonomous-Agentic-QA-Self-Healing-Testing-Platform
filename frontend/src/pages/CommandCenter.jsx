import React, { useState } from 'react';
import { Search } from 'lucide-react';
import { useWorkspace } from '../state/Workspace';
import { pipelineStages } from '../lib/derive';
import WorkflowDiagram, { StageLegend } from '../components/WorkflowDiagram';
import AttackerCard from '../components/AttackerCard';
import RemediationCard from '../components/RemediationCard';
import ValidationCard from '../components/ValidationCard';

export function WorkflowPanel({ onNavigate, title = 'End-to-End Autonomous System Workflow' }) {
  const ws = useWorkspace();
  const { stages, active } = pipelineStages(ws);
  const [query, setQuery] = useState('');

  return (
    <section className="workflow-panel" aria-labelledby="workflow-title">
      <div className="workflow-head">
        <h2 id="workflow-title">{title}</h2>
        <form className="search" role="search" onSubmit={(e) => { e.preventDefault(); onNavigate('audit', { query }); }}>
          <Search size={18} />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search telemetry, findings, or logs..." aria-label="Search telemetry, findings, or logs" />
        </form>
      </div>
      <WorkflowDiagram stages={stages} active={active} onSelect={(s) => onNavigate(s.page)} />
      <StageLegend />
    </section>
  );
}

export default function CommandCenter({ onNavigate }) {
  return (
    <div className="page">
      <WorkflowPanel onNavigate={onNavigate} />
      <div className="cards-row">
        <AttackerCard onOpen={() => onNavigate('attacker')} />
        <RemediationCard onOpen={() => onNavigate('attacker')} />
        <ValidationCard />
      </div>
    </div>
  );
}
