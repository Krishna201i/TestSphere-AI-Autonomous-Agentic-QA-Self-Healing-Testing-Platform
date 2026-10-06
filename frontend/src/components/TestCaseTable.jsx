import React from 'react';

const RECENT_EXECUTIONS = [
  { id: 'exec_20250429_102432', testCaseId: 'TC_LOGIN_001', status: 'healed', duration: '2m 34s', time: '10:24:32' },
  { id: 'exec_20250429_101215', testCaseId: 'TC_CART_002', status: 'failed', duration: '1m 12s', time: '10:12:15' },
  { id: 'exec_20250429_095843', testCaseId: 'TC_CHECKOUT_003', status: 'passed', duration: '3m 18s', time: '09:58:43' },
  { id: 'exec_20250429_093421', testCaseId: 'TC_SEARCH_004', status: 'passed', duration: '1m 45s', time: '09:34:21' },
  { id: 'exec_20250429_091207', testCaseId: 'TC_PROFILE_005', status: 'failed', duration: '2m 11s', time: '09:12:07' },
];

export default function TestCaseTable({ 
  testCases, 
  activeTestCaseId, 
  onSelectTestCase, 
  onRunTest 
}) {
  function renderStatusPill(outcome) {
    const status = (outcome || 'PASSED').toLowerCase();
    let display = 'Passed';
    let pillClass = 'passed';

    if (status === 'healed') {
      display = 'Healed';
      pillClass = 'healed';
    } else if (status === 'failed') {
      display = 'Failed';
      pillClass = 'failed';
    } else if (status === 'pending') {
      display = 'Pending';
      pillClass = 'pending';
    }

    return (
      <span className={`status-pill-small ${pillClass}`}>
        <span className={`dot-indicator ${pillClass}`} />
        <span>{display}</span>
      </span>
    );
  }

  return (
    <section className="tables-grid">
      {/* Left Table: Test Cases */}
      <div className="data-table-card">
        <div className="table-card-header">
          <div className="table-title-area">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#60a5fa" strokeWidth="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
              <line x1="16" y1="13" x2="8" y2="13"></line>
              <line x1="16" y1="17" x2="8" y2="17"></line>
            </svg>
            <h3>Test Cases</h3>
          </div>
          <a href="#view-all-tests" className="view-all-link" onClick={(e) => e.preventDefault()}>View All</a>
        </div>

        <table className="styled-table" id="test-cases-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Test Name</th>
              <th>Category</th>
              <th>Priority</th>
              <th>Version</th>
              <th>Status</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody id="test-cases-tbody">
            {testCases.map((tc) => {
              const isSelected = tc.id === activeTestCaseId;
              const priorityClass = (tc.priority || 'Medium').toLowerCase();

              return (
                <tr 
                  key={tc.id} 
                  style={isSelected ? { background: 'rgba(99, 102, 241, 0.15)' } : {}}
                  onClick={() => onSelectTestCase(tc.id)}
                >
                  <td><code className="mono" style={{ color: '#cbd5e1' }}>{tc.id}</code></td>
                  <td><strong>{tc.name}</strong></td>
                  <td>{tc.category || 'Functional'}</td>
                  <td><span className={`priority-badge ${priorityClass}`}>{tc.priority || 'Medium'}</span></td>
                  <td>{tc.version || '1.0'}</td>
                  <td>{renderStatusPill(tc.outcome)}</td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <button 
                      className="btn-run-small" 
                      onClick={() => onRunTest(tc)}
                    >
                      Run
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Right Table: Recent Executions */}
      <div className="data-table-card">
        <div className="table-card-header">
          <div className="table-title-area">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#a855f7" strokeWidth="2">
              <circle cx="12" cy="12" r="10"></circle>
              <polygon points="10 8 16 12 10 16 10 8"></polygon>
            </svg>
            <h3>Recent Executions</h3>
          </div>
          <a href="#view-all-executions" className="view-all-link" onClick={(e) => e.preventDefault()}>View All</a>
        </div>

        <table className="styled-table" id="executions-table">
          <thead>
            <tr>
              <th>Execution ID</th>
              <th>Test Case</th>
              <th>Status</th>
              <th>Duration</th>
              <th>Started At</th>
            </tr>
          </thead>
          <tbody id="executions-tbody">
            {RECENT_EXECUTIONS.map((ex) => (
              <tr key={ex.id} onClick={() => onSelectTestCase(ex.testCaseId)}>
                <td><code className="mono" style={{ color: '#cbd5e1' }}>{ex.id}</code></td>
                <td>{ex.testCaseId}</td>
                <td>{renderStatusPill(ex.status)}</td>
                <td>{ex.duration}</td>
                <td>{ex.time}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
