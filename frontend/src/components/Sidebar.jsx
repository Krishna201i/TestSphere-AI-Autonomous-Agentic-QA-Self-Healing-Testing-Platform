import React, { useEffect, useState } from 'react';
import {
  CalendarClock, ChartColumn, ChevronRight, CirclePlay, Github, Layers, LayoutDashboard, Puzzle, ScrollText, Settings,
  Shield, Sparkles, Wand2,
} from 'lucide-react';
import { getIntegrations } from '../services/api';

/** The sidebar's pages, in order.  `children` open under their parent. */
export const NAV = [
  { id: 'home', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'autopilot', label: 'Projects', icon: Layers },
  { id: 'runs', label: 'Test Runs', icon: CirclePlay },
  {
    id: 'agents', label: 'AI Agents', icon: Sparkles,
    children: [{ id: 'agents', label: 'Overview' }, { id: 'studio', label: 'Test Studio' }, { id: 'visualizer', label: 'Pipeline' }],
  },
  { id: 'security', label: 'Security', icon: Shield },
  { id: 'healing', label: 'Self-Healing', icon: Wand2 },
  { id: 'reports', label: 'Reports', icon: ChartColumn },
  { id: 'integrations', label: 'Integrations', icon: Puzzle },
];
export const NAV_SECONDARY = [
  { id: 'schedules', label: 'Schedules', icon: CalendarClock },
  { id: 'audit', label: 'Audit log', icon: ScrollText },
  { id: 'profile', label: 'Settings', icon: Settings },
];

export function Logo({ size = 40 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden="true">
      <defs>
        <linearGradient id="logoA" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#3f9a68" />
          <stop offset="100%" stopColor="#123524" />
        </linearGradient>
        <linearGradient id="logoB" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0%" stopColor="#2f7d52" />
          <stop offset="100%" stopColor="#8fd6a8" />
        </linearGradient>
      </defs>
      <path d="M24 3 42 13.5v21L24 45 6 34.5v-21Z" fill="url(#logoA)" />
      <path d="M24 3 42 13.5 24 24 6 13.5Z" fill="url(#logoB)" opacity="0.9" />
      <path d="M24 24v21L6 34.5v-21Z" fill="#17402c" opacity="0.85" />
      <path d="M24 13 33 18.2v10.5L24 34l-9-5.3V18.2Z" fill="#ffffff" opacity="0.92" />
    </svg>
  );
}

/** Whether GitHub is connected (the sidebar's card); null while loading. */
function useGitHub() {
  const [github, setGithub] = useState(null);
  useEffect(() => {
    let alive = true;
    getIntegrations()
      .then((rows) => alive && setGithub(rows.find((r) => r.provider === 'github') || { connected: false }))
      .catch(() => alive && setGithub({ connected: false }));
    return () => { alive = false; };
  }, []);
  return github;
}

function Link({ item, page, onNavigate, sub = false }) {
  const Icon = item.icon;
  const active = page === item.id;
  return (
    <button type="button" className={`side-link ${active ? 'active' : ''}`} aria-current={active ? 'page' : undefined}
      onClick={() => onNavigate(item.id)}>
      {!sub && Icon && <Icon size={18} aria-hidden="true" />}
      {item.label}
    </button>
  );
}

export default function Sidebar({ page, onNavigate, open, onClose }) {
  const github = useGitHub();
  const inGroup = (item) => item.children?.some((c) => c.id === page);
  const [expanded, setExpanded] = useState(() => NAV.filter(inGroup).map((i) => i.id));
  useEffect(() => {
    const group = NAV.find(inGroup);
    if (group) setExpanded((cur) => (cur.includes(group.id) ? cur : [...cur, group.id]));
  }, [page]); // eslint-disable-line react-hooks/exhaustive-deps

  // Escape closes the phone drawer
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const go = (id) => { onNavigate(id); onClose(); };

  return (
    <>
      {open && <button type="button" className="side-scrim" aria-label="Close menu" onClick={onClose} />}
      <aside className={`sidebar ${open ? 'open' : ''}`} aria-label="Sidebar">
        <button type="button" className="side-brand" onClick={() => go('home')}>
          <Logo size={36} />
          <span>
            <span className="side-brand-name">TestSphere AI</span>
            <span className="side-brand-sub">Autonomous QA Platform</span>
          </span>
        </button>

        <nav className="side-nav" aria-label="Main">
          {NAV.map((item) => {
            if (!item.children) return <Link key={item.id} item={item} page={page} onNavigate={go} />;
            const isOpen = expanded.includes(item.id);
            const Icon = item.icon;
            return (
              <div key={item.id} className="side-nav">
                <button type="button" className={`side-link ${inGroup(item) && !isOpen ? 'active' : ''}`} aria-expanded={isOpen}
                  onClick={() => setExpanded((cur) => (isOpen ? cur.filter((id) => id !== item.id) : [...cur, item.id]))}>
                  <Icon size={18} aria-hidden="true" />
                  {item.label}
                  <ChevronRight size={16} className="chev" aria-hidden="true" />
                </button>
                {isOpen && (
                  <div className="side-sub">
                    {item.children.map((c) => <Link key={c.id} item={c} page={page} onNavigate={go} sub />)}
                  </div>
                )}
              </div>
            );
          })}
        </nav>

        <div className="side-sep" />
        <nav className="side-nav" aria-label="More">
          {NAV_SECONDARY.map((item) => <Link key={item.id} item={item} page={page} onNavigate={go} />)}
        </nav>

        {github && (
          <div className="side-card">
            <Github size={22} aria-hidden="true" />
            {github.connected ? (
              <>
                <h4>GitHub connected</h4>
                <p>{github.login ? `As ${github.login}. ` : ''}Fix patches open pull requests and pushes get a status check.</p>
              </>
            ) : (
              <>
                <h4>Connect GitHub</h4>
                <p>Test private repositories, open fix pull requests and report results on every push.</p>
              </>
            )}
            <button type="button" className={`btn btn-sm ${github.connected ? '' : 'btn-primary'}`} onClick={() => go('integrations')}>
              {github.connected ? 'Manage integrations' : 'Connect GitHub'}
            </button>
          </div>
        )}
      </aside>
    </>
  );
}
