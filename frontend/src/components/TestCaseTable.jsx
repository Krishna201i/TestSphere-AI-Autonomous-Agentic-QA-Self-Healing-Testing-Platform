import React, { useState } from 'react';
import { 
  FlaskConical, 
  Play, 
  CheckCircle2, 
  XCircle, 
  Sparkles, 
  Clock, 
  ArrowUpDown,
  ExternalLink
} from 'lucide-react';

export default function TestCaseTable({ 
  testCases, 
  activeTestCaseId, 
  onSelectTestCase, 
  onRunTest 
}) {
  const [statusFilter, setStatusFilter] = useState('ALL');

  const filteredCases = testCases.filter(tc => {
    if (statusFilter === 'ALL') return true;
    return tc.outcome === statusFilter;
  });

  function getStatusBadge(outcome) {
    if (outcome === 'HEALED') {
      return (
        <span className="pill-badge purple">
          <Sparkles size={12} />
          <span>Healed</span>
        </span>
      );
    }
    if (outcome === 'PASSED') {
      return (
        <span className="pill-badge green">
          <CheckCircle2 size={12} />
          <span>Passed</span>
        </span>
      );
    }
    return (
      <span className="pill-badge red">
        <XCircle size={12} />
        <span>Failed</span>
      </span>
    );
  }

  function getPriorityBadge(priority) {
    const p = (priority || 'Medium').toLowerCase();
    return <span className={`priority-tag ${p}`}>{priority || 'Medium'}</span>;
  }

  return (
    <div className="table-panel card-glass">
      <div className="table-header">
        <div className="table-title-group">
          <FlaskConical size={18} className="text-indigo" />
          <h3 className="table-heading">Test Suite Inventory & Execution History</h3>
        </div>

        <div className="table-filter-tabs">
          <button 
            className={`tab-btn ${statusFilter === 'ALL' ? 'active' : ''}`}
            onClick={() => setStatusFilter('ALL')}
          >
            All Tests ({testCases.length})
          </button>
          <button 
            className={`tab-btn ${statusFilter === 'HEALED' ? 'active' : ''}`}
            onClick={() => setStatusFilter('HEALED')}
          >
            Healed ({testCases.filter(c => c.outcome === 'HEALED').length})
          </button>
          <button 
            className={`tab-btn ${statusFilter === 'PASSED' ? 'active' : ''}`}
            onClick={() => setStatusFilter('PASSED')}
          >
            Passed ({testCases.filter(c => c.outcome === 'PASSED').length})
          </button>
          <button 
            className={`tab-btn ${statusFilter === 'FAILED' ? 'active' : ''}`}
            onClick={() => setStatusFilter('FAILED')}
          >
            Failed ({testCases.filter(c => c.outcome === 'FAILED').length})
          </button>
        </div>
      </div>

      <div className="table-wrapper">
        <table className="custom-table">
          <thead>
            <tr>
              <th>Status</th>
              <th>Test ID</th>
              <th>Scenario Name</th>
              <th>Category</th>
              <th>Priority</th>
              <th>Duration</th>
              <th className="text-right">Quick Actions</th>
            </tr>
          </thead>
          <tbody id="test-cases-tbody">
            {filteredCases.map((tc) => {
              const isSelected = tc.id === activeTestCaseId;
              return (
                <tr 
                  key={tc.id} 
                  className={`table-row ${isSelected ? 'row-selected' : ''}`}
                  onClick={() => onSelectTestCase(tc.id)}
                >
                  <td>{getStatusBadge(tc.outcome)}</td>
                  <td className="mono text-muted">{tc.id}</td>
                  <td className="test-name-cell">
                    <span className="name-primary">{tc.name}</span>
                    <span className="name-sub">v{tc.version || '1.0'}</span>
                  </td>
                  <td>
                    <span className="category-pill">{tc.category || 'Functional'}</span>
                  </td>
                  <td>{getPriorityBadge(tc.priority)}</td>
                  <td className="mono text-muted">
                    <div className="duration-cell">
                      <Clock size={13} />
                      <span>{tc.duration || '1m 24s'}</span>
                    </div>
                  </td>
                  <td className="text-right" onClick={(e) => e.stopPropagation()}>
                    <button 
                      className="table-action-btn"
                      onClick={() => onRunTest(tc)}
                      title="Run with Autonomous Agents"
                    >
                      <Play size={13} />
                      <span>Run</span>
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
