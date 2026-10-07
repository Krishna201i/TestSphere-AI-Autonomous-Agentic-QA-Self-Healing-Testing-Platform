import React, { useState } from 'react';
import { 
  FileCode2, 
  Plus, 
  Search, 
  Play, 
  CheckCircle2, 
  XCircle, 
  Wrench, 
  Clock, 
  Filter, 
  Eye, 
  Layers, 
  X,
  Sparkles,
  ChevronRight
} from 'lucide-react';

export default function TestCasesView({ 
  testCases = [], 
  onRunTest, 
  onSelectTestCase, 
  searchQuery = '',
  onOpenPlanModal 
}) {
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [categoryFilter, setCategoryFilter] = useState('ALL');
  const [localSearch, setLocalSearch] = useState('');
  const [selectedCaseForDetail, setSelectedCaseForDetail] = useState(null);
  const [runningCaseId, setRunningCaseId] = useState(null);

  const filterTerm = (searchQuery || localSearch).toLowerCase();

  const filteredCases = testCases.filter(tc => {
    const matchesSearch = tc.name.toLowerCase().includes(filterTerm) ||
      tc.id.toLowerCase().includes(filterTerm) ||
      tc.category.toLowerCase().includes(filterTerm);
    
    const matchesStatus = statusFilter === 'ALL' || tc.outcome === statusFilter;
    const matchesCategory = categoryFilter === 'ALL' || tc.category === categoryFilter;

    return matchesSearch && matchesStatus && matchesCategory;
  });

  const passedCount = testCases.filter(c => c.outcome === 'PASSED').length;
  const healedCount = testCases.filter(c => c.outcome === 'HEALED').length;
  const failedCount = testCases.filter(c => c.outcome === 'FAILED').length;

  function handleQuickRun(tc) {
    setRunningCaseId(tc.id);
    if (onRunTest) {
      onRunTest(tc);
    }
    setTimeout(() => {
      setRunningCaseId(null);
    }, 1800);
  }

  return (
    <div className="view-container">
      {/* Title Header */}
      <div className="page-title-row">
        <div className="page-title-box">
          <div className="page-icon-badge">
            <FileCode2 size={22} />
          </div>
          <div>
            <h2>Test Cases Repository</h2>
            <p>Explore, execute, and inspect autonomous test scenarios & self-healed locators</p>
          </div>
        </div>

        <button 
          className="btn-run-small"
          onClick={onOpenPlanModal}
          style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', cursor: 'pointer' }}
        >
          <Plus size={16} />
          <span>+ Plan New Test</span>
        </button>
      </div>

      {/* KPI Overview Cards */}
      <div className="kpi-grid">
        <div className="kpi-card">
          <div className="kpi-label">Total Test Cases</div>
          <div className="kpi-value">{testCases.length}</div>
          <div className="kpi-footer text-primary">All Test Suites</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Passed Cleanly</div>
          <div className="kpi-value text-success">{passedCount}</div>
          <div className="kpi-footer text-success">Zero Drift</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Self-Healed</div>
          <div className="kpi-value text-healed">{healedCount}</div>
          <div className="kpi-footer text-healed">AI Repaired</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Failed (App Bugs)</div>
          <div className="kpi-value text-danger">{failedCount}</div>
          <div className="kpi-footer text-danger">Requires Fix</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Autonomous Health</div>
          <div className="kpi-value">
            {testCases.length ? Math.round(((passedCount + healedCount) / testCases.length) * 100) : 100}%
          </div>
          <div className="kpi-footer text-cyan">Effective Pass Rate</div>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="filter-bar-card" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
          {/* Status Filter Tabs */}
          <div className="status-tabs">
            <button 
              className={`filter-tab ${statusFilter === 'ALL' ? 'active' : ''}`}
              onClick={() => setStatusFilter('ALL')}
            >
              All ({testCases.length})
            </button>
            <button 
              className={`filter-tab ${statusFilter === 'PASSED' ? 'active' : ''}`}
              onClick={() => setStatusFilter('PASSED')}
            >
              Passed ({passedCount})
            </button>
            <button 
              className={`filter-tab ${statusFilter === 'HEALED' ? 'active' : ''}`}
              onClick={() => setStatusFilter('HEALED')}
            >
              Healed ({healedCount})
            </button>
            <button 
              className={`filter-tab ${statusFilter === 'FAILED' ? 'active' : ''}`}
              onClick={() => setStatusFilter('FAILED')}
            >
              Failed ({failedCount})
            </button>
          </div>

          {/* Search Box */}
          <div className="search-input-wrapper" style={{ width: '320px' }}>
            <Search size={16} className="search-icon-inside" />
            <input 
              type="text" 
              placeholder="Search scenarios or IDs..." 
              value={localSearch}
              onChange={(e) => setLocalSearch(e.target.value)}
              className="form-input with-icon"
            />
          </div>
        </div>

        {/* Categories Bar */}
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', fontWeight: 600 }}>Category:</span>
          {['ALL', 'Authentication', 'E-Commerce', 'Search & Filter', 'User Account'].map(cat => (
            <button
              key={cat}
              className={`category-pill ${categoryFilter === cat ? 'active' : ''}`}
              onClick={() => setCategoryFilter(cat)}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      {/* Test Cases Table Card */}
      <div className="data-table-card">
        <table className="custom-table">
          <thead>
            <tr>
              <th>ID & Name</th>
              <th>Category</th>
              <th>Priority</th>
              <th>Status</th>
              <th>Duration</th>
              <th>AI Diagnostic</th>
              <th style={{ textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredCases.map((tc) => {
              const isHealed = tc.outcome === 'HEALED';
              const isPassed = tc.outcome === 'PASSED';
              const isFailed = tc.outcome === 'FAILED';

              return (
                <tr key={tc.id} className="table-row-hover">
                  <td>
                    <div style={{ display: 'flex', flexDirection: 'column' }}>
                      <span style={{ fontWeight: 600, color: '#ffffff' }}>{tc.name}</span>
                      <span className="mono" style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{tc.id}</span>
                    </div>
                  </td>
                  <td>
                    <span className="env-pill">{tc.category}</span>
                  </td>
                  <td>
                    <span className={`priority-pill priority-${tc.priority.toLowerCase()}`}>
                      {tc.priority}
                    </span>
                  </td>
                  <td>
                    <span className={`status-pill ${
                      isHealed ? 'status-pill-healed' : isPassed ? 'status-pill-passed' : 'status-pill-failed'
                    }`}>
                      {isHealed && <Wrench size={12} />}
                      {isPassed && <CheckCircle2 size={12} />}
                      {isFailed && <XCircle size={12} />}
                      <span>{tc.outcome}</span>
                    </span>
                  </td>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', color: 'var(--text-secondary)', fontSize: '0.82rem' }}>
                      <Clock size={13} />
                      <span>{tc.duration}</span>
                    </div>
                  </td>
                  <td>
                    <span style={{ fontSize: '0.8rem', color: isHealed ? '#c084fc' : isFailed ? '#fb7185' : 'var(--text-muted)' }}>
                      {isHealed ? `Auto-Healed: ${tc.healing?.candidate || 'Selector Drift'}` :
                       isFailed ? tc.failure?.category || 'Execution Failure' :
                       'Deterministic Run'}
                    </span>
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <div style={{ display: 'inline-flex', gap: '0.5rem' }}>
                      <button 
                        className="btn-card-action"
                        onClick={() => setSelectedCaseForDetail(tc)}
                        title="View Execution Details"
                      >
                        <Eye size={14} />
                        <span>Inspect</span>
                      </button>

                      <button 
                        className="btn-primary-small"
                        onClick={() => handleQuickRun(tc)}
                        disabled={runningCaseId === tc.id}
                        title="Execute Test with Playwright"
                      >
                        <Play size={13} />
                        <span>{runningCaseId === tc.id ? 'Running...' : 'Run'}</span>
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Inspect Test Case Modal */}
      {selectedCaseForDetail && (
        <div className="modal-overlay modal-backdrop" onClick={() => setSelectedCaseForDetail(null)}>
          <div className="modal-content modal-card" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '680px' }}>
            <div className="modal-header">
              <div className="modal-title-wrap modal-title-group">
                <Sparkles size={20} className="text-cyan" />
                <div>
                  <h3 className="modal-title">{selectedCaseForDetail.name}</h3>
                  <p className="modal-subtitle">{selectedCaseForDetail.id} • {selectedCaseForDetail.category}</p>
                </div>
              </div>
              <button className="modal-close-btn" onClick={() => setSelectedCaseForDetail(null)}>
                <X size={18} />
              </button>
            </div>

            <div style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
              {/* Outcome summary banner */}
              <div style={{ 
                padding: '0.85rem 1.15rem', 
                borderRadius: 'var(--radius-md)', 
                background: selectedCaseForDetail.outcome === 'HEALED' ? 'rgba(168, 85, 247, 0.15)' :
                            selectedCaseForDetail.outcome === 'PASSED' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(244, 63, 94, 0.15)',
                border: '1px solid ' + (
                  selectedCaseForDetail.outcome === 'HEALED' ? 'rgba(168, 85, 247, 0.4)' :
                  selectedCaseForDetail.outcome === 'PASSED' ? 'rgba(16, 185, 129, 0.4)' : 'rgba(244, 63, 94, 0.4)'
                ),
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center'
              }}>
                <div>
                  <div style={{ fontWeight: 700, color: '#ffffff' }}>Outcome: {selectedCaseForDetail.outcome}</div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    Execution Duration: {selectedCaseForDetail.duration}
                  </div>
                </div>
                <button 
                  className="btn-primary-small"
                  onClick={() => {
                    handleQuickRun(selectedCaseForDetail);
                    setSelectedCaseForDetail(null);
                  }}
                >
                  <Play size={13} />
                  <span>Re-Run Now</span>
                </button>
              </div>

              {/* Failure & Healing breakdown */}
              {selectedCaseForDetail.healing && selectedCaseForDetail.outcome === 'HEALED' && (
                <div style={{ background: 'rgba(16, 26, 48, 0.6)', border: '1px solid rgba(168, 85, 247, 0.3)', borderRadius: 'var(--radius-md)', padding: '1rem' }}>
                  <div style={{ fontSize: '0.84rem', fontWeight: 700, color: '#c084fc', marginBottom: '0.5rem' }}>
                    Self-Healing Diagnostic Breakdown
                  </div>
                  <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginBottom: '0.75rem' }}>
                    {selectedCaseForDetail.failure?.rootCause}
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                    <div style={{ background: 'rgba(244, 63, 94, 0.1)', padding: '0.65rem', borderRadius: 'var(--radius-sm)', border: '1px solid rgba(244, 63, 94, 0.3)' }}>
                      <span style={{ fontSize: '0.72rem', color: '#fb7185', fontWeight: 700 }}>OLD SELECTOR</span>
                      <div className="mono" style={{ fontSize: '0.8rem', color: '#ffffff', marginTop: '0.2rem' }}>
                        {selectedCaseForDetail.healing.oldSelector}
                      </div>
                    </div>
                    <div style={{ background: 'rgba(16, 185, 129, 0.1)', padding: '0.65rem', borderRadius: 'var(--radius-sm)', border: '1px solid rgba(16, 185, 129, 0.3)' }}>
                      <span style={{ fontSize: '0.72rem', color: '#34d399', fontWeight: 700 }}>REPAIRED SELECTOR</span>
                      <div className="mono" style={{ fontSize: '0.8rem', color: '#ffffff', marginTop: '0.2rem' }}>
                        {selectedCaseForDetail.healing.newSelector}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Execution Logs */}
              <div>
                <div style={{ fontSize: '0.84rem', fontWeight: 700, color: 'var(--text-main)', marginBottom: '0.5rem' }}>
                  Execution Step Stream
                </div>
                <div className="console-log-box" style={{ maxHeight: '200px', overflowY: 'auto' }}>
                  {selectedCaseForDetail.logs?.map((l, i) => (
                    <div key={i} className={`log-line log-${l.type || 'default'}`}>
                      <span className="log-time">{l.time}</span>
                      <span className="log-text">{l.text}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="modal-footer" style={{ border: 'none', padding: 0 }}>
                <button className="btn-secondary" onClick={() => setSelectedCaseForDetail(null)}>
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
