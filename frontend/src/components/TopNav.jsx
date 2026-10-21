import React from 'react';
import { Bell, ChevronDown, Search } from 'lucide-react';
import { useWorkspace, OPERATOR } from '../state/Workspace';
import { healthStats, pct } from '../lib/derive';

export const PAGES = [
  { id: 'command', label: 'Command Center' },
  { id: 'pipeline', label: 'Pipeline Visualizer' },
  { id: 'attacker', label: 'Attacker Agent' },
  { id: 'remediation', label: 'Remediation Bridge' },
  { id: 'validation', label: 'Validation Engine' },
  { id: 'audit', label: 'Audit & Logs' },
];

export function Logo({ size = 40 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden="true">
      <defs>
        <linearGradient id="logoA" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#7c5cf5" />
          <stop offset="100%" stopColor="#2d2a8c" />
        </linearGradient>
        <linearGradient id="logoB" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0%" stopColor="#4f7df0" />
          <stop offset="100%" stopColor="#a78bfa" />
        </linearGradient>
      </defs>
      <path d="M24 3 42 13.5v21L24 45 6 34.5v-21Z" fill="url(#logoA)" />
      <path d="M24 3 42 13.5 24 24 6 13.5Z" fill="url(#logoB)" opacity="0.9" />
      <path d="M24 24v21L6 34.5v-21Z" fill="#3b2f9e" opacity="0.85" />
      <path d="M24 13 33 18.2v10.5L24 34l-9-5.3V18.2Z" fill="#fff" opacity="0.92" />
    </svg>
  );
}

export default function TopNav({ page, onNavigate }) {
  const { health, audit } = useWorkspace();
  const h = healthStats(health);
  const recent = audit.filter((a) => Date.now() - new Date(a.at).getTime() < 3600_000).length;

  return (
    <header className="topbar">
      <div className="brand">
        <Logo />
        <span className="brand-name">TESTSPHERE AI</span>
      </div>
      <span className="brand-divider" />
      <div className="workspace-status" aria-live="polite">
        <div className="live"><span className={`dot ${h.online ? '' : 'off'}`} /> {h.online ? 'Live Workspace' : 'Backend Offline'}</div>
        <div className="health">
          SYS_HEALTH: {h.online
            ? <span className="ok-text">OK ({pct(h.successRate)})</span>
            : <span className="bad-text">DOWN ({pct(h.successRate)})</span>}
        </div>
      </div>

      <nav className="navpills" aria-label="Main">
        {PAGES.map((p) => (
          <button key={p.id} type="button" className={`navpill ${page === p.id ? 'active' : ''}`}
            aria-current={page === p.id ? 'page' : undefined} onClick={() => onNavigate(p.id)}>
            {p.label}
          </button>
        ))}
      </nav>

      <div className="topbar-right">
        <button type="button" className="env-select" onClick={() => onNavigate('audit')} title="Search audit log">
          <Search size={18} />
          <span className="sep" />
          <span className="env-label">env: {import.meta.env.MODE} [main]</span>
          <ChevronDown size={16} />
        </button>
        <button type="button" className="icon-btn" aria-label={`${recent} audit events in the last hour`} onClick={() => onNavigate('audit')}>
          <Bell size={21} />
          {recent > 0 && <span className="badge">{recent > 99 ? '99+' : recent}</span>}
        </button>
        <div className="user">
          <span className="avatar">DA</span>
          <span className="name">{OPERATOR}</span>
        </div>
      </div>
    </header>
  );
}
