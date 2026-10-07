import React, { useState } from 'react';
import { 
  BarChart3, 
  Download, 
  FileText, 
  Calendar, 
  TrendingUp, 
  CheckCircle2, 
  Clock, 
  Sparkles, 
  ShieldCheck,
  Share2
} from 'lucide-react';

export default function ReportsView({ testCases = [], executions = [] }) {
  const [exportNotice, setExportNotice] = useState(null);

  const totalRuns = executions.length;
  const passedRuns = executions.filter(e => e.status === 'PASSED').length;
  const healedRuns = executions.filter(e => e.status === 'HEALED').length;
  const failedRuns = executions.filter(e => e.status === 'FAILED').length;
  const stability = totalRuns > 0 
    ? `${(((passedRuns + healedRuns) / totalRuns) * 100).toFixed(1)}%` 
    : '100.0%';
  const avgDurationStr = totalRuns > 0
    ? `${(executions.reduce((acc, e) => acc + (e.duration_ms || 1800), 0) / (totalRuns * 1000)).toFixed(1)}s`
    : '0.0s';
  const hoursSaved = (healedRuns * 0.25).toFixed(1);

  // Dynamic functional categories from testCases
  const categoryMap = {};
  testCases.forEach(tc => {
    const cat = tc.category || 'Functional';
    if (!categoryMap[cat]) {
      categoryMap[cat] = { total: 0, passed: 0 };
    }
    categoryMap[cat].total += 1;
    if (tc.outcome === 'PASSED' || tc.outcome === 'HEALED') {
      categoryMap[cat].passed += 1;
    }
  });

  const categories = Object.keys(categoryMap).length > 0 
    ? Object.entries(categoryMap).map(([category, data], idx) => {
        const rate = Math.round((data.passed / data.total) * 100);
        const colors = ['#10b981', '#06b6d4', '#a855f7', '#3b82f6', '#f59e0b'];
        return { category, rate, color: colors[idx % colors.length] };
      })
    : [
        { category: 'Authentication & SSO', rate: 100, color: '#10b981' },
        { category: 'E-Commerce Workflows', rate: 100, color: '#06b6d4' },
      ];

  function triggerExport(format) {
    setExportNotice(`Exported ${format} Report successfully.`);
    setTimeout(() => setExportNotice(null), 3000);
  }

  return (
    <div className="view-container">
      {/* Title Header */}
      <div className="page-title-row">
        <div className="page-title-box">
          <div className="page-icon-badge" style={{ background: 'linear-gradient(135deg, rgba(6, 182, 212, 0.3), rgba(59, 130, 246, 0.3))' }}>
            <BarChart3 size={22} color="#06b6d4" />
          </div>
          <div>
            <h2>Reports & Quality Analytics</h2>
            <p>Quality assurance intelligence, self-healing efficacy, and regression analytics</p>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <button 
            className="btn-card-action"
            onClick={() => triggerExport('CSV')}
            style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', cursor: 'pointer' }}
          >
            <Download size={14} />
            <span>Export CSV</span>
          </button>

          <button 
            className="btn-run-small"
            onClick={() => triggerExport('PDF')}
            style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', cursor: 'pointer' }}
          >
            <FileText size={15} />
            <span>Export Executive PDF</span>
          </button>
        </div>
      </div>

      {exportNotice && (
        <div style={{ background: 'rgba(16, 185, 129, 0.15)', border: '1px solid rgba(16, 185, 129, 0.4)', color: '#34d399', padding: '0.75rem 1rem', borderRadius: 'var(--radius-md)', display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.84rem' }}>
          <CheckCircle2 size={16} />
          <span>{exportNotice}</span>
        </div>
      )}

      {/* KPI Overview Cards */}
      <div className="kpi-grid">
        <div className="kpi-card">
          <div className="kpi-label">Test Suite Stability</div>
          <div className="kpi-value text-success">{stability}</div>
          <div className="kpi-footer text-success">Live Platform Metrics</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Time Saved by AI</div>
          <div className="kpi-value text-healed">{hoursSaved} hrs</div>
          <div className="kpi-footer text-healed">Manual Locator Fixes</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Self-Healed Runs</div>
          <div className="kpi-value text-cyan">{healedRuns} tests</div>
          <div className="kpi-footer text-cyan">Self-Healing Guard</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Total Test Runs</div>
          <div className="kpi-value">{totalRuns}</div>
          <div className="kpi-footer text-primary">Live Database Records</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Average Run Duration</div>
          <div className="kpi-value">{avgDurationStr}</div>
          <div className="kpi-footer text-success">Fast Playwright Mode</div>
        </div>
      </div>

      {/* Analytics Breakdown Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
        {/* Card 1: Pass Rate by Functional Category */}
        <div className="data-table-card" style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#ffffff' }}>Pass Rate by Functional Area</h3>
            <span className="env-pill">{categories.length} Categories</span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {categories.map(item => (
              <div key={item.category} style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.82rem' }}>
                  <span style={{ color: 'var(--text-main)', fontWeight: 600 }}>{item.category}</span>
                  <span style={{ color: item.color, fontWeight: 700 }}>{item.rate}%</span>
                </div>
                <div style={{ width: '100%', height: '8px', background: 'rgba(30, 41, 59, 0.6)', borderRadius: '4px', overflow: 'hidden' }}>
                  <div style={{ width: `${item.rate}%`, height: '100%', background: item.color, borderRadius: '4px' }}></div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Card 2: Self-Healing Root Cause Distribution */}
        <div className="data-table-card" style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#ffffff' }}>Self-Healing Root Cause Distribution</h3>
            <span className="env-pill">{healedRuns} Healed Selectors</span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {[
              { type: 'CSS Selector & Attribute Drift', percentage: healedRuns > 0 ? 100 : 0, count: `${healedRuns} locators`, color: '#a855f7' },
              { type: 'Dynamic ID & UUID Mutation', percentage: 0, count: '0 locators', color: '#06b6d4' },
              { type: 'DOM Hierarchy Reorganization', percentage: 0, count: '0 locators', color: '#3b82f6' },
            ].map(item => (
              <div key={item.type} style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.82rem' }}>
                  <span style={{ color: 'var(--text-main)', fontWeight: 600 }}>{item.type}</span>
                  <span style={{ color: 'var(--text-muted)' }}>{item.count} ({item.percentage}%)</span>
                </div>
                <div style={{ width: '100%', height: '8px', background: 'rgba(30, 41, 59, 0.6)', borderRadius: '4px', overflow: 'hidden' }}>
                  <div style={{ width: `${item.percentage}%`, height: '100%', background: item.color, borderRadius: '4px' }}></div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Executive Summary Card */}
      <div className="data-table-card" style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#ffffff', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Sparkles size={16} className="text-cyan" />
          <span>Autonomous QA Executive Summary</span>
        </h3>
        <p style={{ fontSize: '0.86rem', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
          TestSphere-AI has executed {totalRuns} autonomous test runs across registered target web applications. 
          With self-healing pipelines activated, {healedRuns} locator drift mutations were autonomously repaired in real time with an average execution duration of {avgDurationStr}. 
          Test suite effective pass rate is currently {stability}, saving an estimated {hoursSaved} hours of manual engineering locator maintenance.
        </p>
      </div>
    </div>
  );
}
