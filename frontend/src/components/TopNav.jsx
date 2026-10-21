import React, { useEffect, useRef, useState } from 'react';
import { Bell, ChevronDown, Search, Server, UserRound } from 'lucide-react';
import { useWorkspace } from '../state/Workspace';
import { API_BASE_LABEL } from '../services/api';
import { healthStats, pct, timeAgo, toDate } from '../lib/derive';

export const PAGES = [
  { id: 'command', label: 'Command Center' },
  { id: 'pipeline', label: 'Pipeline Visualizer' },
  { id: 'attacker', label: 'Attacker Agent' },
  { id: 'remediation', label: 'Remediation Bridge' },
  { id: 'validation', label: 'Validation Engine' },
  { id: 'audit', label: 'Audit & Logs' },
];

const SEEN_KEY = 'testsphere.notifications.seen';

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

/** Menu anchored under its trigger; closes on outside click or Escape. */
function Popover({ open, onClose, children, label, width = 360 }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => { if (ref.current && !ref.current.parentElement.contains(e.target)) onClose(); };
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, onClose]);
  if (!open) return null;
  return <div ref={ref} className="popover" role="dialog" aria-label={label} style={{ width }}>{children}</div>;
}

function useMenu() {
  const [open, setOpen] = useState(null);
  return { open, toggle: (id) => setOpen((cur) => (cur === id ? null : id)), close: () => setOpen(null) };
}

function loadSeen() {
  try {
    return Number(localStorage.getItem(SEEN_KEY)) || 0;
  } catch {
    return 0;
  }
}

export default function TopNav({ page, onNavigate }) {
  const { health, audit, system, operator, setOperator } = useWorkspace();
  const h = healthStats(health);
  const menu = useMenu();
  const [seenAt, setSeenAt] = useState(loadSeen);
  const [draftName, setDraftName] = useState(operator);
  const unread = audit.filter((a) => toDate(a.at).getTime() > seenAt).length;

  useEffect(() => setDraftName(operator), [operator]);

  function openNotifications() {
    menu.toggle('bell');
    const now = Date.now();
    setSeenAt(now);
    try {
      localStorage.setItem(SEEN_KEY, String(now));
    } catch {
      // badge just reappears on reload
    }
  }

  function go(id, params) {
    menu.close();
    onNavigate(id, params);
  }

  const initials = operator.split(/[\s._-]+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('') || '?';
  const envLabel = system ? `env: ${system.environment} [${system.commit || 'main'}]` : `env: ${import.meta.env.MODE} [offline]`;

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
        {/* Environment / connection */}
        <div className="menu-anchor">
          <button type="button" className="env-select" aria-expanded={menu.open === 'env'} onClick={() => menu.toggle('env')}>
            <Search size={18} />
            <span className="sep" />
            <span className="env-label">{envLabel}</span>
            <ChevronDown size={16} />
          </button>
          <Popover open={menu.open === 'env'} onClose={menu.close} label="Environment">
            <div className="popover-head"><Server size={16} /> Connected backend</div>
            <dl className="kv small">
              <dt>API</dt><dd className="mono">{API_BASE_LABEL}</dd>
              <dt>Status</dt><dd>{h.online ? <span className="ok-text">online · {h.latency}ms</span> : <span className="bad-text">unreachable</span>}</dd>
              {system ? (
                <>
                  <dt>Version</dt><dd>{system.commit || 'unknown'} · API v{system.api_version}</dd>
                  <dt>Environment</dt><dd>{system.environment} · {system.database}</dd>
                  <dt>LLM</dt><dd>{system.llm.provider} / {system.llm.model}{system.llm.provider === 'mock' && <span className="muted"> (offline, scripted)</span>}</dd>
                  <dt>Scan scope</dt><dd>{system.scan_scope.join(', ')}</dd>
                  <dt>Ingestion</dt><dd>{system.ingestion.git_hosts.join(', ')}{system.ingestion.local_paths ? ' · local folders' : ''}</dd>
                  <dt>Memory</dt><dd>{system.memory_backend}</dd>
                </>
              ) : (
                <><dt>Version</dt><dd className="bad-text">This backend has no /api/system — it is running older code.</dd></>
              )}
            </dl>
          </Popover>
        </div>

        {/* Notifications */}
        <div className="menu-anchor">
          <button type="button" className="icon-btn" aria-expanded={menu.open === 'bell'}
            aria-label={`Notifications${unread ? `, ${unread} new` : ''}`} onClick={openNotifications}>
            <Bell size={21} />
            {unread > 0 && <span className="badge">{unread > 99 ? '99+' : unread}</span>}
          </button>
          <Popover open={menu.open === 'bell'} onClose={menu.close} label="Notifications" width={400}>
            <div className="popover-head">Notifications</div>
            {audit.length === 0 ? <div className="empty">Nothing yet.</div> : (
              <ul className="notif-list">
                {audit.slice(0, 8).map((a) => (
                  <li key={a.id}>
                    <span className={`timeline-mark mark ${a.level}`} />
                    <div>
                      <div className="notif-msg">{a.message}</div>
                      <div className="small muted">{a.kind}{a.actor ? ` · ${a.actor}` : ''} · {timeAgo(a.at)}</div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <button type="button" className="btn btn-sm" style={{ width: '100%' }} onClick={() => go('audit')}>View all in Audit &amp; Logs</button>
          </Popover>
        </div>

        {/* Profile */}
        <div className="menu-anchor">
          <button type="button" className="user" aria-expanded={menu.open === 'profile'} onClick={() => menu.toggle('profile')}>
            <span className="avatar">{initials}</span>
            <span className="name">{operator}</span>
          </button>
          <Popover open={menu.open === 'profile'} onClose={menu.close} label="Profile" width={320}>
            <div className="popover-head"><UserRound size={16} /> Operator</div>
            <form onSubmit={(e) => { e.preventDefault(); setOperator(draftName); menu.close(); }} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <label className="field">
                Name recorded on approvals, scans and retests
                <input className="input" value={draftName} onChange={(e) => setDraftName(e.target.value)} maxLength={64} />
              </label>
              <button type="submit" className="btn btn-primary btn-sm">Save</button>
            </form>
            <p className="hint" style={{ margin: '10px 0 0' }}>
              There is no login yet: this name is trusted as typed and stored in this browser only.
            </p>
            <div className="popover-links">
              <button type="button" className="tab" onClick={() => go('audit', { query: operator })}>My activity</button>
              <button type="button" className="tab" onClick={() => menu.toggle('env')}>Connection</button>
            </div>
          </Popover>
        </div>
      </div>
    </header>
  );
}
