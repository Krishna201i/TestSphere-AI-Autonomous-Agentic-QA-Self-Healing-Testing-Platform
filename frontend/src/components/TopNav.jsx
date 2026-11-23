import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Bell, ChevronDown, Github, LogOut, Menu, Monitor, Moon, Search, Server, Sun, UserRound } from 'lucide-react';
import { useWorkspace } from '../state/Workspace';
import { useAuth } from '../state/Auth';
import { THEMES, useTheme } from '../state/theme';
import { API_BASE_LABEL } from '../services/api';
import { healthStats, pct, timeAgo, toDate } from '../lib/derive';
import { searchWorkspace } from '../lib/dashboard';
import { NAV, NAV_SECONDARY } from './Sidebar';

export { Logo } from './Sidebar';

/** Every page and its title (the sidebar's pages, their sub-pages, and pages reached by link). */
export const PAGES = [
  ...NAV.flatMap((n) => (n.children ? n.children.map((c) => ({ id: c.id, label: c.id === 'agents' ? 'AI Agents' : c.label })) : [n])),
  ...NAV_SECONDARY,
].filter((p, i, all) => all.findIndex((q) => q.id === p.id) === i).map(({ id, label }) => ({ id, label }));

const SEEN_KEY = 'testsphere.notifications.seen';

/** Menu anchored under its trigger; closes on outside click or Escape. */
function Popover({ open, onClose, children, label, size = '' }) {
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
  return <div ref={ref} className={`popover ${size}`} role="dialog" aria-label={label}>{children}</div>;
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

/** Search projects, runs, tests and findings; Ctrl/Cmd+K focuses it. */
function SearchBox({ onNavigate }) {
  const ws = useWorkspace();
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(0);
  const input = useRef(null);
  const hits = useMemo(() => searchWorkspace(ws, query), [ws, query]);
  const isMac = typeof navigator !== 'undefined' && /Mac/.test(navigator.platform);

  useEffect(() => {
    const onKey = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        input.current?.focus();
        setOpen(true);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);
  useEffect(() => setCursor(0), [query]);

  function choose(hit) {
    setOpen(false);
    setQuery('');
    onNavigate(hit.page, hit.tab ? { tab: hit.tab } : null);
  }

  function onKeyDown(e) {
    if (e.key === 'ArrowDown') { e.preventDefault(); setCursor((c) => Math.min(c + 1, hits.length - 1)); }
    if (e.key === 'ArrowUp') { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)); }
    if (e.key === 'Enter' && hits[cursor]) { e.preventDefault(); choose(hits[cursor]); }
    if (e.key === 'Escape') { setOpen(false); input.current?.blur(); }
  }

  return (
    <div className="search-box menu-anchor">
      <label className="search-field">
        <Search size={16} aria-hidden="true" />
        <span className="visually-hidden">Search projects, runs, tests and issues</span>
        <input ref={input} type="search" value={query} placeholder="Search projects, runs, issues…" role="combobox"
          aria-expanded={open && query.trim() !== ''} aria-controls="search-results" aria-autocomplete="list"
          aria-activedescendant={open && hits[cursor] ? `search-hit-${cursor}` : undefined}
          onChange={(e) => { setQuery(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)} onKeyDown={onKeyDown} />
        <span className="kbd" aria-hidden="true">{isMac ? '⌘ K' : 'Ctrl K'}</span>
      </label>
      {open && query.trim() !== '' && (
        <div className="popover search-results" id="search-results" role="listbox" aria-label="Search results">
          {hits.length === 0 ? <div className="empty">Nothing matches “{query.trim()}”.</div> : hits.map((h, i) => (
            <button key={`${h.kind}-${h.label}-${i}`} id={`search-hit-${i}`} type="button" role="option" aria-selected={i === cursor}
              className={`search-hit ${i === cursor ? 'active' : ''}`} onMouseDown={(e) => e.preventDefault()} onClick={() => choose(h)}>
              <span className="pill gray">{h.kind}</span>
              <span className="stack-sm">
                <span>{h.label}</span>
                {h.detail && <span className="small muted">{h.detail}</span>}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function TopNav({ page, onNavigate, onMenu }) {
  const { health, audit, system, operator, setOperator } = useWorkspace();
  const auth = useAuth();
  const signedIn = auth.mode === 'firebase';
  const displayName = (signedIn ? (auth.user.name || auth.user.email) : operator) || 'Account';
  const h = healthStats(health);
  const menu = useMenu();
  const [theme, setTheme] = useTheme();
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

  const initials = displayName.split(/[\s._@-]+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('') || '?';
  const status = !h.online ? ['off', 'Offline'] : h.dbDown ? ['warn', 'Degraded'] : ['', 'Operational'];

  return (
    <header className="topbar shell-top">
      <button type="button" className="icon-btn menu-btn" aria-label="Open menu" onClick={onMenu}>
        <Menu size={20} />
      </button>

      <SearchBox onNavigate={onNavigate} />

      <div className="topbar-right">
        <button type="button" className="icon-btn gh-btn" aria-label="GitHub integration" onClick={() => onNavigate('integrations')}>
          <Github size={18} />
        </button>

        {/* System status and connection details */}
        <div className="menu-anchor" aria-live="polite">
          <button type="button" className="status-chip" aria-expanded={menu.open === 'env'} onClick={() => menu.toggle('env')}
            aria-label={`System status: ${status[1]}`}>
            <span className={`dot ${status[0]}`} />
            <span className="status-text">{status[1]}</span>
            <ChevronDown size={14} aria-hidden="true" />
          </button>
          <Popover open={menu.open === 'env'} onClose={menu.close} label="System status">
            <div className="popover-head"><Server size={16} /> Connected backend</div>
            <dl className="kv small">
              <dt>API</dt><dd className="mono">{API_BASE_LABEL}</dd>
              <dt>Status</dt><dd>{h.online ? <span className="ok-text">online · {h.latency} ms · {pct(h.successRate, 0)} of recent checks</span> : <span className="bad-text">unreachable</span>}</dd>
              <dt>Database</dt><dd>{h.dbDown ? <span className="warn-text">{h.dbError}</span> : h.online ? <span className="ok-text">connected</span> : '—'}</dd>
              {system ? (
                <>
                  <dt>Version</dt><dd>{system.commit || 'unknown'} · API v{system.api_version}</dd>
                  {system.environment && <><dt>Environment</dt><dd>{system.environment} · {system.database}</dd></>}
                  {system.llm && <><dt>AI model</dt><dd>{system.llm.provider} / {system.llm.model}{system.llm.provider === 'mock' && <span className="muted"> (offline, scripted)</span>}</dd></>}
                  {system.scan_scope && <><dt>Scan scope</dt><dd>{system.scan_scope.join(', ')}</dd></>}
                  {system.ingestion && <><dt>Ingestion</dt><dd>{(system.ingestion.git_hosts || []).join(', ')}{system.ingestion.local_paths ? ' · local folders' : ''}</dd></>}
                  {system.memory_backend && <><dt>Memory</dt><dd>{system.memory_backend}</dd></>}
                </>
              ) : system === false ? (
                <><dt>Version</dt><dd className="bad-text">This backend has no /api/system, so it is running older code.</dd></>
              ) : (
                <><dt>Version</dt><dd className="muted">Not loaded yet</dd></>
              )}
            </dl>
          </Popover>
        </div>

        {/* Notifications */}
        <div className="menu-anchor">
          <button type="button" className="icon-btn" aria-expanded={menu.open === 'bell'}
            aria-label={`Notifications${unread ? `, ${unread} new` : ''}`} onClick={openNotifications}>
            <Bell size={18} />
            {unread > 0 && <span className="badge">{unread > 99 ? '99+' : unread}</span>}
          </button>
          <Popover open={menu.open === 'bell'} onClose={menu.close} label="Notifications" size="wide">
            <div className="popover-head">Notifications</div>
            {audit.length === 0 ? <div className="empty">Nothing yet.</div> : (
              <ul className="notif-list">
                {audit.slice(0, 8).map((a) => (
                  <li key={a.id}>
                    <span className={`mark ${a.level}`} />
                    <div>
                      <div className="notif-msg">{a.message}</div>
                      <div className="small muted">{a.kind}{a.actor ? ` · ${a.actor}` : ''} · {timeAgo(a.at)}</div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <button type="button" className="btn btn-sm btn-block" onClick={() => go('audit')}>View all in Audit</button>
          </Popover>
        </div>

        {/* Profile */}
        <div className="menu-anchor">
          <button type="button" className="user" aria-expanded={menu.open === 'profile'} onClick={() => menu.toggle('profile')}>
            {signedIn && auth.user.photo
              ? <img className="avatar" src={auth.user.photo} alt="" referrerPolicy="no-referrer" />
              : <span className="avatar">{initials}</span>}
            <span className="name">{displayName}</span>
          </button>
          <Popover open={menu.open === 'profile'} onClose={menu.close} label="Profile" size="narrow">
            {signedIn ? (
              <>
                <div className="popover-head"><UserRound size={16} /> Signed in</div>
                <div>
                  <div className="strong">{auth.user.name || auth.user.email}</div>
                  {auth.user.name && <div className="small muted cell-wrap">{auth.user.email}</div>}
                </div>
                <p className="hint m-0">Your verified identity is recorded on approvals, scans, retests and pipeline runs.</p>
              </>
            ) : (
              <>
                <div className="popover-head"><UserRound size={16} /> Operator</div>
                <form className="form-stack" onSubmit={(e) => { e.preventDefault(); setOperator(draftName); menu.close(); }}>
                  <label className="field">
                    Name recorded on approvals, scans and retests
                    <input className="input" value={draftName} onChange={(e) => setDraftName(e.target.value)} maxLength={64} />
                  </label>
                  <button type="submit" className="btn btn-primary btn-sm">Save</button>
                </form>
                <p className="hint m-0">Sign-in is off on this server (single local user), so this name is trusted as typed.</p>
              </>
            )}
            <div className="popover-links">
              <button type="button" className="chip" onClick={() => go('profile')}>Profile</button>
              <button type="button" className="chip" onClick={() => go('audit', { query: displayName })}>My activity</button>
              <button type="button" className="chip" onClick={() => go('privacy')}>Privacy</button>
            </div>
            <div className="menu-sep" />
            <div className="row-between small">
              <span className="muted">Theme</span>
              <div className="tabs" role="radiogroup" aria-label="Theme">
                {THEMES.map(([id, label]) => (
                  <button key={id} type="button" role="radio" aria-checked={theme === id} className={`tab ${theme === id ? 'active' : ''}`}
                    onClick={() => setTheme(id)}>
                    {id === 'system' ? <Monitor size={13} /> : id === 'light' ? <Sun size={13} /> : <Moon size={13} />} {label}
                  </button>
                ))}
              </div>
            </div>
            {signedIn && (
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => { menu.close(); auth.signOut(); }}>
                <LogOut size={14} /> Sign out
              </button>
            )}
          </Popover>
        </div>
      </div>
    </header>
  );
}
