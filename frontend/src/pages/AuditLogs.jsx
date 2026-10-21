import React, { useEffect, useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import { useWorkspace } from '../state/Workspace';

const KINDS = ['all', 'scan', 'approval', 'retest', 'qa', 'target', 'execution'];

export default function AuditLogs({ params }) {
  const { audit, executions, testCases, lastScan } = useWorkspace();
  const [query, setQuery] = useState(params?.query || '');
  const [kind, setKind] = useState('all');

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
    const findingEntries = (lastScan?.findings || []).map((f) => ({
      id: `finding-${f.key}`,
      at: f.detected_at,
      kind: 'scan',
      level: ['critical', 'high'].includes(f.severity) ? 'error' : 'warn',
      message: `[${f.severity.toUpperCase()}] ${f.check_id} · ${f.title} · ${f.component}`,
    }));
    return [...audit, ...execEntries, ...findingEntries].sort((a, b) => new Date(b.at) - new Date(a.at));
  }, [audit, executions, lastScan, testCases]); // eslint-disable-line react-hooks/exhaustive-deps

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
          <p>Who approved what, every scan and retest, and every test execution — in one timeline.</p>
        </div>
        <button type="button" className="btn" onClick={exportJson} disabled={!shown.length}>Export JSON</button>
      </div>

      <section className="card">
        <div className="form-row" style={{ alignItems: 'center' }}>
          <div className="search" style={{ flex: 1, minWidth: 220 }}>
            <Search size={18} />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search telemetry, findings, or logs..." aria-label="Search logs" />
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
                <span className="when" title={new Date(e.at).toLocaleString()}>
                  {new Date(e.at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}<br />{new Date(e.at).toLocaleTimeString()}
                </span>
                <span className={`mark ${e.level}`} />
                <span className="cell-wrap"><span className="kind">{e.kind}</span>{e.message}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
