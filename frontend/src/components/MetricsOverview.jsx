import React from 'react';

export default function MetricsOverview({ stats }) {
  return (
    <section className="kpi-grid">
      {/* KPI 1: Total Executions */}
      <div className="kpi-card executions">
        <div className="kpi-card-top">
          <div className="kpi-icon-circle">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
              <polygon points="5 3 19 12 5 21 5 3"></polygon>
            </svg>
          </div>
          <span className="kpi-label">Total Executions</span>
        </div>
        <div className="kpi-card-mid">
          <span className="kpi-number" id="kpi-total-exec">{stats.totalTests || '128'}</span>
          <span className="kpi-trend positive">↑ +12%</span>
        </div>
        <div className="kpi-card-bot">
          <span>89% Active</span>
          <svg className="kpi-mini-wave" viewBox="0 0 80 20" fill="none">
            <path d="M0 15 Q 20 5, 40 12 T 80 6" stroke="#38bdf8" strokeWidth="2" fill="none" strokeLinecap="round" />
          </svg>
        </div>
      </div>

      {/* KPI 2: Passed */}
      <div className="kpi-card passed">
        <div className="kpi-card-top">
          <div className="kpi-icon-circle">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
          </div>
          <span className="kpi-label">Passed</span>
        </div>
        <div className="kpi-card-mid">
          <span className="kpi-number" id="kpi-passed">86</span>
        </div>
        <div className="kpi-card-bot">
          <span>{stats.passRate || 67}%</span>
          <div className="kpi-progress-bar">
            <div className="kpi-progress-fill green" style={{ width: `${stats.passRate || 67}%` }}></div>
          </div>
        </div>
      </div>

      {/* KPI 3: Failed */}
      <div className="kpi-card failed">
        <div className="kpi-card-top">
          <div className="kpi-icon-circle">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </div>
          <span className="kpi-label">Failed</span>
        </div>
        <div className="kpi-card-mid">
          <span className="kpi-number" id="kpi-failed">24</span>
        </div>
        <div className="kpi-card-bot">
          <span>19%</span>
          <div className="kpi-progress-bar">
            <div className="kpi-progress-fill red" style={{ width: '19%' }}></div>
          </div>
        </div>
      </div>

      {/* KPI 4: Healed */}
      <div className="kpi-card healed">
        <div className="kpi-card-top">
          <div className="kpi-icon-circle">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"></path>
            </svg>
          </div>
          <span className="kpi-label">Healed</span>
        </div>
        <div className="kpi-card-mid">
          <span className="kpi-number" id="kpi-healed">{stats.healedCount || 16}</span>
        </div>
        <div className="kpi-card-bot">
          <span>92% Confidence</span>
          <div className="kpi-progress-bar">
            <div className="kpi-progress-fill purple" style={{ width: '92%' }}></div>
          </div>
        </div>
      </div>

      {/* KPI 5: Avg Duration */}
      <div className="kpi-card duration">
        <div className="kpi-card-top">
          <div className="kpi-icon-circle">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10"></circle>
              <polyline points="12 6 12 12 16 14"></polyline>
            </svg>
          </div>
          <span className="kpi-label">Avg. Duration</span>
        </div>
        <div className="kpi-card-mid">
          <span className="kpi-number" id="kpi-duration">{stats.avgDuration || '2m 34s'}</span>
          <span className="kpi-trend negative">↓ -18%</span>
        </div>
        <div className="kpi-card-bot">
          <span>Fast</span>
          <svg className="kpi-mini-wave" viewBox="0 0 80 20" fill="none">
            <path d="M0 16 Q 25 4, 45 10 T 80 4" stroke="#22d3ee" strokeWidth="2" fill="none" strokeLinecap="round" />
          </svg>
        </div>
      </div>
    </section>
  );
}
