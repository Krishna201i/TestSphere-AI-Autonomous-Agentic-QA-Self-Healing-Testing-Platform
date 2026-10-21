import React from 'react';
import AttackerAgent from './AttackerAgent';
import RemediationBridge from './RemediationBridge';
import ValidationEngine from './ValidationEngine';
import { useWorkspace } from '../state/Workspace';

/** Find → fix → verify: the three security stages on one page. */
export const SECURITY_TABS = [
  { id: 'attacker', label: 'Attacker Agent', hint: 'Find', view: AttackerAgent },
  { id: 'remediation', label: 'Remediation', hint: 'Fix', view: RemediationBridge },
  { id: 'validation', label: 'Validation', hint: 'Verify', view: ValidationEngine },
];

export default function Security({ onNavigate, params }) {
  const { findings } = useWorkspace();
  const tab = SECURITY_TABS.find((t) => t.id === params?.tab) || SECURITY_TABS[0];
  const counts = {
    attacker: findings.filter((f) => f.status === 'open').length,
    remediation: findings.filter((f) => f.status === 'open' && f.remediation && !f.approved_by).length,
    validation: findings.filter((f) => f.approved_by && f.retest_result !== 'pass').length,
  };
  const View = tab.view;
  return (
    <>
      <div className="subnav">
        <div className="tabs" role="tablist" aria-label="Security stages">
          {SECURITY_TABS.map((t) => (
            <button key={t.id} type="button" role="tab" aria-selected={t.id === tab.id}
              className={`tab ${t.id === tab.id ? 'active' : ''}`} onClick={() => onNavigate('security', { tab: t.id })}>
              <span className="muted-on-tab">{t.hint} ·</span> {t.label}{counts[t.id] ? ` (${counts[t.id]})` : ''}
            </button>
          ))}
        </div>
      </div>
      <View onNavigate={onNavigate} params={params} />
    </>
  );
}
