import React from 'react';
import LoopPanel from '../components/PipelineLoop';
import AttackerCard from '../components/AttackerCard';
import RemediationCard from '../components/RemediationCard';
import ValidationCard from '../components/ValidationCard';

export default function CommandCenter({ onNavigate }) {
  return (
    <div className="page">
      <LoopPanel onNavigate={onNavigate} />
      <div className="cards-row">
        <ValidationCard onNavigate={onNavigate} />
        <AttackerCard onOpen={() => onNavigate('attacker')} />
        <RemediationCard onOpen={() => onNavigate('attacker')} />
      </div>
    </div>
  );
}
