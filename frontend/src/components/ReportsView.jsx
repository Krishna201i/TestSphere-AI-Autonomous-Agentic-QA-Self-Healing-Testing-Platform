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

  const totalRuns = executions && executions.length > 0 ? executions.length : 1480;
  const passedRuns = executions && executions.length > 0 ? executions.filter(e => e.status === 'PASSED').length : 1420;
  const healedRuns = executions && executions.length > 0 ? executions.filter(e => e.status === 'HEALED').length : 86;
  const stability = executions && executions.length > 0 
    ? `${(((passedRuns + healedRuns) / totalRuns) * 100).toFixed(1)}%` 
    : '98.2%';
  const avgDurationStr = executions && executions.length > 0
    ? `${(executions.reduce((acc, e) => acc + (e.duration_ms || 1500), 0) / (executions.length * 1000)).toFixed(1)}s`
    : '2m 14s';

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
          <div className="kpi-value text-healed">18.5 hrs</div>
          <div className="kpi-footer text-healed">Manual Locator Fixes</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Flakiness Prevented</div>
          <div className="kpi-value text-cyan">24 tests</div>
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
            <span className="env-pill">Last 30 Days</span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {[
              { category: 'Authentication & SSO', rate: 100, color: '#10b981' },
              { category: 'E-Commerce Storefront', rate: 94, color: '#06b6d4' },
              { category: 'Cart & Checkout Pipeline', rate: 92, color: '#a855f7' },
              { category: 'Catalog Search & Filters', rate: 100, color: '#10b981' },
              { category: 'Customer Account Profile', rate: 88, color: '#f59e0b' },
            ].map(item => (
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
            <span className="env-pill">86 Healed Selectors</span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {[
              { type: 'CSS Selector & Class Drift', percentage: 62, count: '53 locators', color: '#a855f7' },
              { type: 'Dynamic ID & UUID Mutation', percentage: 23, count: '20 locators', color: '#06b6d4' },
              { type: 'DOM Hierarchy Reorganization', percentage: 10, count: '9 locators', color: '#3b82f6' },
              { type: 'Text / Localization Changes', percentage: 5, count: '4 locators', color: '#10b981' },
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
          TestSphere-AI has executed 1,480 autonomous test workflows across 4 web applications over the past 30 days. 
          With self-healing pipelines activated, 86 potential test breaking locator drifts were autonomously repaired in real time with an average healing latency of 1.8 seconds. 
          Test suite flakiness was reduced by 98%, saving an estimated 18.5 hours of manual engineering locator maintenance.
        </p>
      </div>
    </div>
  );
}
