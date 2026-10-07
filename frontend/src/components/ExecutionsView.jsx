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
import { getTestExecutions } from '../services/api';

const DEFAULT_EXECUTIONS = [
  {
    id: 'exec_20261007_102432',
    testName: 'User Login & Auth Flow',
    app: 'E-Commerce Storefront',
    browser: 'Playwright Chromium Headless',
    status: 'HEALED',
    duration: '2m 34s',
    timestamp: 'Today at 10:24 AM',
    initiator: 'Autonomous Agent',
    logsCount: 10,
    logs: [
      { time: '10:24:03', text: 'Starting execution: TC_LOGIN_001', type: 'info' },
      { time: '10:24:05', text: 'Navigating to https://example.com/login', type: 'default' },
      { time: '10:24:28', text: 'Locator timeout: #login-btn not found. Triggering Failure Analyzer Agent...', type: 'warn' },
      { time: '10:24:30', text: 'Agent diagnosed LOCATOR_CHANGED (Confidence: 92%)', type: 'agent' },
      { time: '10:24:32', text: 'Synthesized: button[type="submit"]', type: 'agent' },
      { time: '10:24:38', text: 'Validation SUCCESS! Test step healed & persisted to database.', type: 'success' },
    ]
  },
  {
    id: 'exec_20261007_101200',
    testName: 'Add Item to Cart Scenario',
    app: 'E-Commerce Storefront',
    browser: 'Playwright Chromium Headless',
    status: 'FAILED',
    duration: '1m 12s',
    timestamp: 'Today at 10:12 AM',
    initiator: 'CI/CD Pipeline #482',
    logsCount: 5,
    logs: [
      { time: '10:12:00', text: 'Starting execution: TC_CART_002', type: 'info' },
      { time: '10:12:08', text: 'Clicking button[data-testid="add-to-cart"]', type: 'default' },
      { time: '10:12:12', text: 'Server returned HTTP 500 Internal Server Error', type: 'error' },
      { time: '10:12:14', text: 'Categorized as APPLICATION_BUG. Non-healable.', type: 'error' },
    ]
  },
  {
    id: 'exec_20261007_095810',
    testName: 'Complete Checkout & Order Confirmation',
    app: 'E-Commerce Storefront',
    browser: 'Playwright Chromium Headless',
    status: 'PASSED',
    duration: '3m 18s',
    timestamp: 'Today at 09:58 AM',
    initiator: 'Autonomous Agent',
    logsCount: 5,
    logs: [
      { time: '09:58:10', text: 'Starting execution: TC_CHECKOUT_003', type: 'info' },
      { time: '09:58:25', text: 'Filling shipping and payment form...', type: 'default' },
      { time: '09:58:43', text: 'Order confirmation #ord-9821 received. All assertions passed.', type: 'success' },
    ]
  },
  {
    id: 'exec_20261007_093421',
    testName: 'Search Product Catalog Grid',
    app: 'E-Commerce Storefront',
    browser: 'Playwright Chromium Headless',
    status: 'PASSED',
    duration: '1m 45s',
    timestamp: 'Today at 09:34 AM',
    initiator: 'Scheduled Run',
    logsCount: 3,
    logs: [
      { time: '09:34:21', text: 'Starting execution: TC_SEARCH_004', type: 'info' },
      { time: '09:34:30', text: '12 items verified in catalog grid. Passed.', type: 'success' },
    ]
  },
  {
    id: 'exec_20261007_084511',
    testName: 'Account MFA Verification',
    app: 'FinTech Banking Portal',
    browser: 'Playwright Chromium Headless',
    status: 'HEALED',
    duration: '2m 10s',
    timestamp: 'Today at 08:45 AM',
    initiator: 'Autonomous Agent',
    logsCount: 7,
    logs: [
      { time: '08:45:11', text: 'Starting execution: TC_MFA_008', type: 'info' },
      { time: '08:45:25', text: 'OTP input box relocated from form#otp to input[name="token"]', type: 'warn' },
      { time: '08:45:30', text: 'Self-healing selector successfully updated. Passed.', type: 'success' },
    ]
  }
];

export default function ExecutionsView({ onOpenPlanModal, searchQuery = '' }) {
  const [executions, setExecutions] = useState(DEFAULT_EXECUTIONS);
  const [localSearch, setLocalSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [selectedLogExec, setSelectedLogExec] = useState(null);
  const [reRunningId, setReRunningId] = useState(null);

  useEffect(() => {
    async function loadExecutions() {
      const live = await getTestExecutions();
      if (live && live.length > 0) {
        const mapped = live.map(e => ({
          id: `exec_${e.id}`,
          testName: e.test_case_name || `Execution #${e.id}`,
          app: 'E-Commerce Storefront',
          browser: 'Playwright Chromium Headless',
          status: e.status || 'PASSED',
          duration: `${(e.duration_ms / 1000).toFixed(1)}s`,
          timestamp: 'Recent',
          initiator: 'Autonomous Agent',
          logsCount: 4,
          logs: [
            { time: '10:00:00', text: 'Execution started', type: 'info' },
            { time: '10:00:02', text: `Status: ${e.status}`, type: e.status === 'PASSED' ? 'success' : 'error' },
          ]
        }));
        setExecutions([...mapped, ...DEFAULT_EXECUTIONS]);
      }
    }
    loadExecutions();
  }, []);

  const filterTerm = (searchQuery || localSearch).toLowerCase();
  const filtered = executions.filter(e => {
    const matchesSearch = e.id.toLowerCase().includes(filterTerm) ||
      e.testName.toLowerCase().includes(filterTerm) ||
      e.app.toLowerCase().includes(filterTerm);
    const matchesStatus = statusFilter === 'ALL' || e.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  function handleReRun(exec) {
    setReRunningId(exec.id);
    setTimeout(() => {
      setReRunningId(null);
    }, 1500);
  }

  return (
    <div className="view-container">
      {/* Title Header */}
      <div className="page-title-row">
        <div className="page-title-box">
          <div className="page-icon-badge">
            <PlayCircle size={22} />
          </div>
          <div>
            <h2>Test Executions</h2>
            <p>Live execution history, multi-agent telemetry streams, and run telemetry</p>
          </div>
        </div>

        <button 
          className="btn-run-small"
          onClick={onOpenPlanModal}
          style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', cursor: 'pointer' }}
        >
          <Play size={15} />
          <span>+ Trigger New Run</span>
        </button>
      </div>

      {/* KPI Overview Cards */}
      <div className="kpi-grid">
        <div className="kpi-card">
          <div className="kpi-label">Total Executions</div>
          <div className="kpi-value">{executions.length}</div>
          <div className="kpi-footer text-primary">All Sessions</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Pass Rate</div>
          <div className="kpi-value text-success">94.2%</div>
          <div className="kpi-footer text-success">High Stability</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Auto-Healed Runs</div>
          <div className="kpi-value text-healed">18</div>
          <div className="kpi-footer text-healed">Saved Pipeline Runs</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Average Run Time</div>
          <div className="kpi-value">2m 14s</div>
          <div className="kpi-footer text-cyan">Fast Execution</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Active Engine</div>
          <div className="kpi-value">Playwright</div>
          <div className="kpi-footer text-success">Chromium 128</div>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="filter-bar-card">
        <div className="status-tabs">
          <button 
            className={`filter-tab ${statusFilter === 'ALL' ? 'active' : ''}`}
            onClick={() => setStatusFilter('ALL')}
          >
            All Runs
          </button>
          <button 
            className={`filter-tab ${statusFilter === 'PASSED' ? 'active' : ''}`}
            onClick={() => setStatusFilter('PASSED')}
          >
            Passed
          </button>
          <button 
            className={`filter-tab ${statusFilter === 'HEALED' ? 'active' : ''}`}
            onClick={() => setStatusFilter('HEALED')}
          >
            Healed
          </button>
          <button 
            className={`filter-tab ${statusFilter === 'FAILED' ? 'active' : ''}`}
            onClick={() => setStatusFilter('FAILED')}
          >
            Failed
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
            {filtered.map((e) => {
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
                    <div style={{ display: 'inline-flex', gap: '0.45rem' }}>
                      <button 
                        className="btn-card-action"
                        onClick={() => setSelectedLogExec(e)}
                        title="View Telemetry Logs"
                      >
                        <Terminal size={14} />
                        <span>Logs</span>
                      </button>

                      <button 
                        className="btn-primary-small"
                        onClick={() => handleReRun(e)}
                        disabled={reRunningId === e.id}
                        title="Re-run test scenario"
                      >
                        <RotateCw size={13} className={reRunningId === e.id ? 'spin-icon' : ''} />
                        <span>{reRunningId === e.id ? 'Running' : 'Re-run'}</span>
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Execution Logs Modal */}
      {selectedLogExec && (
        <div className="modal-overlay modal-backdrop" onClick={() => setSelectedLogExec(null)}>
          <div className="modal-content modal-card" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '650px' }}>
            <div className="modal-header">
              <div className="modal-title-wrap modal-title-group">
                <Terminal size={20} className="text-cyan" />
                <div>
                  <h3 className="modal-title">Execution Telemetry Stream</h3>
                  <p className="modal-subtitle">{selectedLogExec.id} • {selectedLogExec.testName}</p>
                </div>
              </div>
              <button className="modal-close-btn" onClick={() => setSelectedLogExec(null)}>
                <X size={18} />
              </button>
            </div>

            <div style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span className="env-pill">{selectedLogExec.browser}</span>
                <span className={`status-pill ${
                  selectedLogExec.status === 'HEALED' ? 'status-pill-healed' :
                  selectedLogExec.status === 'PASSED' ? 'status-pill-passed' : 'status-pill-failed'
                }`}>
                  {selectedLogExec.status}
                </span>
              </div>

              <div className="console-log-box" style={{ maxHeight: '280px', overflowY: 'auto' }}>
                {selectedLogExec.logs.map((l, i) => (
                  <div key={i} className={`log-line log-${l.type || 'default'}`}>
                    <span className="log-time">{l.time}</span>
                    <span className="log-text">{l.text}</span>
                  </div>
                ))}
              </div>

              <div className="modal-footer" style={{ border: 'none', padding: 0 }}>
                <button className="btn-secondary" onClick={() => setSelectedLogExec(null)}>
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
