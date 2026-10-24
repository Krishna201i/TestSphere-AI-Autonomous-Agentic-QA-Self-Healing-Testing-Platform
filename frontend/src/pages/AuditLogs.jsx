import React, { useEffect, useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import { useWorkspace } from '../state/Workspace';
import { toDate } from '../lib/derive';
import usePersistentState from '../lib/usePersistentState';

const KINDS = ['all', 'scan', 'approval', 'retest', 'qa', 'target', 'execution'];

export default function AuditLogs({ params }) {
  const { audit, executions, testCases } = useWorkspace();
  const [query, setQuery] = useState(params?.query || '');
  const [kind, setKind] = usePersistentState('audit.kind', 'all');

  useEffect(() => {
    if (params?.query != null) setQuery(params.query);
  }, [params]);

  const nameOf = (id) => testCases.find((t) => t.id === id)?.name || `Test case #${id}`;

  // Merge workspace audit events with backend execution records
  const entries = useMemo(() => {
    const execEntries = executions
      .filter((e) => e.completed_at || e.created_at)
      .map((e) => ({
        id: `exec-${e.id}`,
        at: e.completed_at || e.created_at,
        kind: 'execution',
        level: e.status === 'FAILED' ? 'error' : e.status === 'HEALED' ? 'warn' : e.status === 'PASSED' ? 'success' : 'info',
        message: `Execution #${e.id} · ${nameOf(e.test_case_id)} → ${e.status}${e.error_message ? ` · ${e.error_message}` : ''}`,
      }));
    // QA runs started from the dashboard are already audited server-side
    const audited = new Set(audit.filter((a) => a.kind === 'qa' && a.ref).map((a) => `exec-${a.ref}`));
    return [...audit, ...execEntries.filter((e) => !audited.has(e.id))].sort((a, b) => toDate(b.at) - toDate(a.at));
  }, [audit, executions, testCases]); // eslint-disable-line react-hooks/exhaustive-deps

  const q = query.trim().toLowerCase();
  const shown = entries.filter((e) => (kind === 'all' || e.kind === kind) && (!q || e.message.toLowerCase().includes(q)));

  function exportJson() {
    const blob = new Blob([JSON.stringify(shown, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `testsphere-audit-${new Date().toISOString().slice(0, 19)}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  return (
    <div className="page">
      <div className="page-title">
        <div>
          <h1>Audit &amp; Logs</h1>
          <p>Who approved what, every scan and retest, and every test execution — stored on the server, in one timeline.</p>
        </div>
        <button type="button" className="btn" onClick={exportJson} disabled={!shown.length}>Export JSON</button>
      </div>

      <section className="card">
        <div className="form-row center">
          <div className="search">
            <Search size={18} />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search logs" aria-label="Search logs" />
          </div>
          <div className="tabs" role="tablist" aria-label="Filter by type">
            {KINDS.map((k) => (
              <button key={k} type="button" role="tab" aria-selected={kind === k} className={`tab ${kind === k ? 'active' : ''}`} onClick={() => setKind(k)}>{k}</button>
            ))}
          </div>
        </div>
        <div className="muted small">{shown.length} of {entries.length} entries</div>
        {shown.length === 0 ? <div className="empty">Nothing matches.</div> : (
          <ul className="timeline">
            {shown.slice(0, 300).map((e) => (
              <li key={e.id}>
                <span className="when" title={toDate(e.at).toLocaleString()}>
                  {toDate(e.at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}<br />{toDate(e.at).toLocaleTimeString()}
                </span>
                <span className={`mark ${e.level}`} />
                <span className="cell-wrap"><span className="kind">{e.kind}{e.actor ? ` · ${e.actor}` : ''}</span>{e.message}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
