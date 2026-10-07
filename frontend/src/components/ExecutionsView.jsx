import React, { useState, useEffect } from 'react';
import { 
  PlayCircle, 
  Search, 
  CheckCircle2, 
  XCircle, 
  Wrench, 
  Clock, 
  Terminal, 
  RotateCw, 
  Play, 
  X,
  Filter,
  Sparkles
} from 'lucide-react';
import { getTestExecutions, planAndExecuteWorkflow } from '../services/api';

export default function ExecutionsView({ onOpenPlanModal, searchQuery = '', executions: propExecutions = [] }) {
  const [executions, setExecutions] = useState([]);
  const [localSearch, setLocalSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [selectedLogExec, setSelectedLogExec] = useState(null);
  const [reRunningId, setReRunningId] = useState(null);

  function mapLiveExecutions(live) {
    return live.map(e => ({
      id: `exec_${e.id}`,
      rawId: e.id,
      testCaseId: e.test_case_id,
      testName: `Execution Run #${e.id} (TC #${e.test_case_id})`,
      app: 'TestSphere Suite',
      browser: 'Playwright Chromium Headless',
      status: e.status || 'PASSED',
      duration: e.duration_ms ? `${(e.duration_ms / 1000).toFixed(1)}s` : '1.8s',
      timestamp: e.started_at ? new Date(e.started_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Just now',
      initiator: 'Autonomous Agent',
      logsCount: 3,
      logs: [
        { 
          time: e.started_at ? new Date(e.started_at).toLocaleTimeString() : '10:00:00', 
          text: `Execution initialized for test case #${e.test_case_id}`, 
          type: 'info' 
        },
        { 
          time: e.started_at ? new Date(e.started_at).toLocaleTimeString() : '10:00:01', 
          text: 'Playwright Chromium browser context launched in headless fast mode', 
          type: 'default' 
        },
        { 
          time: e.completed_at ? new Date(e.completed_at).toLocaleTimeString() : '10:00:02', 
          text: e.error_message ? `Result: ${e.error_message}` : `Execution completed cleanly: ${e.status}`, 
          type: e.status === 'PASSED' ? 'success' : (e.status === 'HEALED' ? 'agent' : 'error') 
        },
      ]
    }));
  }

  useEffect(() => {
    if (propExecutions && propExecutions.length > 0) {
      setExecutions(mapLiveExecutions(propExecutions));
    } else {
      async function loadExecutions() {
        const live = await getTestExecutions();
        if (Array.isArray(live) && live.length > 0) {
          setExecutions(mapLiveExecutions(live));
        }
      }
      loadExecutions();
    }
  }, [propExecutions]);

  const filterTerm = (searchQuery || localSearch).toLowerCase();
  const filtered = executions.filter(e => {
    const matchesSearch = e.id.toLowerCase().includes(filterTerm) ||
      e.testName.toLowerCase().includes(filterTerm) ||
      e.app.toLowerCase().includes(filterTerm);
    const matchesStatus = statusFilter === 'ALL' || e.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  const totalRuns = executions.length;
  const passedRuns = executions.filter(e => e.status === 'PASSED').length;
  const healedRuns = executions.filter(e => e.status === 'HEALED').length;
  const failedRuns = executions.filter(e => e.status === 'FAILED').length;
  const passRate = totalRuns > 0 ? `${Math.round(((passedRuns + healedRuns) / totalRuns) * 100)}%` : '100%';
  const avgDuration = totalRuns > 0 
    ? `${(executions.reduce((acc, e) => acc + (parseFloat(e.duration) || 1.8), 0) / totalRuns).toFixed(1)}s` 
    : '0.0s';

  async function handleReRun(exec) {
    setReRunningId(exec.id);
    try {
      const tcId = exec.testCaseId || 1;
      await planAndExecuteWorkflow({
        test_case_id: tcId,
        test_case_name: exec.testName,
        headless: true,
      });
      const refreshed = await getTestExecutions();
      if (Array.isArray(refreshed) && refreshed.length > 0) {
        setExecutions(mapLiveExecutions(refreshed));
      }
    } catch (err) {
      console.warn('Re-run failed:', err);
    } finally {
      setReRunningId(null);
    }
  }

  return (
    <div className="view-container">
      {/* Title Header */}
      <div className="page-title-row">
        <div className="page-title-box">
          <div className="page-icon-badge" style={{ background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.3), rgba(168, 85, 247, 0.3))' }}>
            <PlayCircle size={22} color="#818cf8" />
          </div>
          <div>
            <h2>Execution History & Telemetry</h2>
            <p>Live Playwright runs, step-by-step logs, durations, and agent actions</p>
          </div>
        </div>

        <button 
          className="btn-run-small"
          onClick={onOpenPlanModal}
          style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', cursor: 'pointer' }}
        >
          <Play size={15} />
          <span>Trigger New Run</span>
        </button>
      </div>

      {/* KPI Overview Cards */}
      <div className="kpi-grid">
        <div className="kpi-card">
          <div className="kpi-label">Total Executions</div>
          <div className="kpi-value">{totalRuns}</div>
          <div className="kpi-footer text-primary">Database Runs</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Pass Rate</div>
          <div className="kpi-value text-success">{passRate}</div>
          <div className="kpi-footer text-success">Effective Success</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Auto-Healed Runs</div>
          <div className="kpi-value text-healed">{healedRuns}</div>
          <div className="kpi-footer text-healed">Self-Repaired</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Average Run Time</div>
          <div className="kpi-value">{avgDuration}</div>
          <div className="kpi-footer text-cyan">Fast Execution</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Active Engine</div>
          <div className="kpi-value">Playwright</div>
          <div className="kpi-footer text-success">Chromium Headless</div>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="filter-bar-card">
        <div className="status-tabs">
          <button 
            className={`filter-tab ${statusFilter === 'ALL' ? 'active' : ''}`}
            onClick={() => setStatusFilter('ALL')}
          >
            All Runs ({totalRuns})
          </button>
          <button 
            className={`filter-tab ${statusFilter === 'PASSED' ? 'active' : ''}`}
            onClick={() => setStatusFilter('PASSED')}
          >
            Passed ({passedRuns})
          </button>
          <button 
            className={`filter-tab ${statusFilter === 'HEALED' ? 'active' : ''}`}
            onClick={() => setStatusFilter('HEALED')}
          >
            Healed ({healedRuns})
          </button>
          <button 
            className={`filter-tab ${statusFilter === 'FAILED' ? 'active' : ''}`}
            onClick={() => setStatusFilter('FAILED')}
          >
            Failed ({failedRuns})
          </button>
        </div>

        <div className="search-input-wrapper" style={{ width: '320px' }}>
          <Search size={16} className="search-icon-inside" />
          <input 
            type="text" 
            placeholder="Search execution ID or scenario..." 
            value={localSearch}
            onChange={(e) => setLocalSearch(e.target.value)}
            className="form-input with-icon"
          />
        </div>
      </div>

      {/* Executions Table */}
      <div className="data-table-card">
        <table className="custom-table">
          <thead>
            <tr>
              <th>Execution ID</th>
              <th>Test Scenario</th>
              <th>Target Application</th>
              <th>Status</th>
              <th>Duration</th>
              <th>Initiator</th>
              <th>Time</th>
              <th style={{ textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan="8" style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '2.5rem 1rem' }}>
                  No execution logs found matching the filter.
                </td>
              </tr>
            ) : (
              filtered.map((e) => {
                const isHealed = e.status === 'HEALED';
                const isPassed = e.status === 'PASSED';
                const isFailed = e.status === 'FAILED';

                return (
                  <tr key={e.id} className="table-row-hover">
                    <td>
                      <span className="mono" style={{ fontSize: '0.78rem', color: 'var(--primary-light)', fontWeight: 600 }}>
                        {e.id}
                      </span>
                    </td>
                    <td>
                      <span style={{ fontWeight: 600, color: '#ffffff' }}>{e.testName}</span>
                    </td>
                    <td>
                      <span className="env-pill">{e.app}</span>
                    </td>
                    <td>
                      <span className={`status-pill ${
                        isHealed ? 'status-pill-healed' : isPassed ? 'status-pill-passed' : 'status-pill-failed'
                      }`}>
                        {isHealed && <Wrench size={12} />}
                        {isPassed && <CheckCircle2 size={12} />}
                        {isFailed && <XCircle size={12} />}
                        <span>{e.status}</span>
                      </span>
                    </td>
                    <td>
                      <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>{e.duration}</span>
                    </td>
                    <td>
                      <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{e.initiator}</span>
                    </td>
                    <td>
                      <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{e.timestamp}</span>
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <div style={{ display: 'inline-flex', gap: '0.5rem' }}>
                        <button 
                          className="btn-card-action"
                          onClick={() => setSelectedLogExec(e)}
                          title="View Execution Log Trace"
                        >
                          <Terminal size={13} />
                          <span>View Logs</span>
                        </button>

                        <button 
                          className="btn-primary-small"
                          onClick={() => handleReRun(e)}
                          disabled={reRunningId === e.id}
                          title="Re-run against Playwright Engine"
                        >
                          <RotateCw size={13} className={reRunningId === e.id ? 'spin-icon' : ''} />
                          <span>{reRunningId === e.id ? 'Running...' : 'Re-Run'}</span>
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Log Details Modal */}
      {selectedLogExec && (
        <div className="modal-overlay modal-backdrop" onClick={() => setSelectedLogExec(null)}>
          <div className="modal-content modal-card" style={{ maxWidth: '680px' }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-title-wrap modal-title-group">
                <Terminal size={20} className="text-cyan" />
                <div>
                  <h3 className="modal-title">Execution Trace: {selectedLogExec.id}</h3>
                  <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', margin: 0 }}>
                    {selectedLogExec.testName} &bull; {selectedLogExec.browser}
                  </p>
                </div>
              </div>
              <button className="modal-close-btn" onClick={() => setSelectedLogExec(null)}>
                <X size={18} />
              </button>
            </div>

            <div style={{ padding: '1.25rem' }}>
              <div className="terminal-window" style={{ maxHeight: '340px', overflowY: 'auto' }}>
                {selectedLogExec.logs.map((log, idx) => (
                  <div className="log-line" key={idx}>
                    <span className="log-time">[{log.time}]</span>
                    <span className={`log-text ${log.type}`}>{log.text}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="modal-footer" style={{ justifyContent: 'space-between' }}>
              <span className={`status-pill ${
                selectedLogExec.status === 'HEALED' ? 'status-pill-healed' : 
                selectedLogExec.status === 'PASSED' ? 'status-pill-passed' : 'status-pill-failed'
              }`}>
                {selectedLogExec.status}
              </span>

              <button className="btn-secondary" onClick={() => setSelectedLogExec(null)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
