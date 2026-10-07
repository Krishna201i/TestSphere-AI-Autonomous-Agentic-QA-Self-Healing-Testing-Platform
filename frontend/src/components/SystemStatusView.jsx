import React, { useState } from 'react';
import { 
  Activity, 
  Cpu, 
  Server, 
  Database, 
  CheckCircle2, 
  Zap, 
  Radio, 
  HardDrive, 
  ShieldCheck, 
  RefreshCw, 
  Sparkles,
  Bot
} from 'lucide-react';

export default function SystemStatusView({ backendStatus = false }) {
  const [isRefreshing, setIsRefreshing] = useState(false);

  function handleRefresh() {
    setIsRefreshing(true);
    setTimeout(() => setIsRefreshing(false), 800);
  }

  const agents = [
    {
      name: 'Planner Agent',
      role: 'Autonomous Test Planning & Scenario Synthesis',
      model: 'Gemini 3.8 Flash (High Reasoning)',
      status: 'ACTIVE',
      latency: '320ms',
      throughput: '142 tps',
      uptime: '99.98%'
    },
    {
      name: 'Execution Engine Agent',
      role: 'Headless Browser Orchestration & DOM Interactions',
      model: 'Playwright v1.49 (Chromium Engine)',
      status: 'ACTIVE',
      latency: '1.2s avg step',
      throughput: '4 Parallel Workers',
      uptime: '100%'
    },
    {
      name: 'Failure Analyzer Agent',
      role: 'Root Cause Classification & Multimodal DOM Diffing',
      model: 'Vision + DOM Tree AST Analyzer',
      status: 'ACTIVE',
      latency: '410ms',
      throughput: '94.8% Accuracy',
      uptime: '99.95%'
    },
    {
      name: 'Self-Healing Engine Agent',
      role: 'Selector Synthesis & In-Memory Sandbox Validation',
      model: 'Dynamic CSS/XPath Heuristic Synthesizer',
      status: 'ACTIVE',
      latency: '1.8s healing cycle',
      throughput: '92.4% Recovery Rate',
      uptime: '99.99%'
    }
  ];

  return (
    <div className="view-container">
      {/* Title Header */}
      <div className="page-title-row">
        <div className="page-title-box">
          <div className="page-icon-badge" style={{ background: 'linear-gradient(135deg, rgba(16, 185, 129, 0.3), rgba(6, 182, 212, 0.3))' }}>
            <Activity size={22} color="#10b981" />
          </div>
          <div>
            <h2>System Status & Agent Fleet</h2>
            <p>Multi-agent telemetry, engine health, and infrastructure diagnostics</p>
          </div>
        </div>

        <button 
          className="btn-card-action"
          onClick={handleRefresh}
          style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', cursor: 'pointer' }}
        >
          <RefreshCw size={14} className={isRefreshing ? 'spin-icon' : ''} />
          <span>Refresh Telemetry</span>
        </button>
      </div>

      {/* KPI Overview Cards */}
      <div className="kpi-grid">
        <div className="kpi-card">
          <div className="kpi-label">Agent Fleet Health</div>
          <div className="kpi-value text-success">100%</div>
          <div className="kpi-footer text-success">4 / 4 Agents Active</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">FastAPI Backend</div>
          <div className="kpi-value" style={{ fontSize: '1.15rem' }}>
            {backendStatus ? 'Connected' : 'Simulated'}
          </div>
          <div className="kpi-footer text-cyan">
            {backendStatus ? 'Live REST & SSE' : 'Sandbox Fallback'}
          </div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">API Latency</div>
          <div className="kpi-value text-primary">38ms</div>
          <div className="kpi-footer text-primary">Fast Roundtrip</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Playwright Workers</div>
          <div className="kpi-value text-healed">4 Active</div>
          <div className="kpi-footer text-healed">Headless Chromium</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Platform Uptime</div>
          <div className="kpi-value">99.98%</div>
          <div className="kpi-footer text-success">Zero Outages</div>
        </div>
      </div>

      {/* Agent Fleet Grid */}
      <div>
        <h3 style={{ fontSize: '1.05rem', fontWeight: 700, color: '#ffffff', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Bot size={18} className="text-cyan" />
          <span>Autonomous AI Agent Fleet</span>
        </h3>

        <div className="projects-grid">
          {agents.map((agent) => (
            <div key={agent.name} className="project-card">
              <div className="project-card-header">
                <div className="project-title-group">
                  <div className="project-badge-icon" style={{ background: 'linear-gradient(135deg, #4f46e5, #06b6d4)' }}>
                    <Bot size={18} />
                  </div>
                  <div>
                    <h3 className="project-title">{agent.name}</h3>
                    <div className="project-meta-row">
                      <span className="repo-pill">{agent.model}</span>
                    </div>
                  </div>
                </div>

                <div className="status-pill status-pill-passed">
                  <span className="status-dot-pulse"></span>
                  <span>{agent.status}</span>
                </div>
              </div>

              <p className="project-description">{agent.role}</p>

              <div className="project-stats-row">
                <div className="project-stat-item">
                  <span className="stat-label">Inference Latency</span>
                  <span className="stat-val text-cyan">{agent.latency}</span>
                </div>
                <div className="project-stat-item">
                  <span className="stat-label">Metric</span>
                  <span className="stat-val">{agent.throughput}</span>
                </div>
                <div className="project-stat-item">
                  <span className="stat-label">Uptime</span>
                  <span className="stat-val text-success">{agent.uptime}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Infrastructure Services Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '1.25rem' }}>
        <div className="data-table-card" style={{ padding: '1.25rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Server size={18} className="text-cyan" />
              <span style={{ fontWeight: 700, color: '#ffffff' }}>FastAPI API Gateway</span>
            </div>
            <span className={`status-pill ${backendStatus ? 'status-pill-passed' : 'status-pill-healed'}`}>
              {backendStatus ? 'ONLINE' : 'SANDBOX'}
            </span>
          </div>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
            High-performance async Python backend orchestrating agents, tests, and database persistence.
          </p>
        </div>

        <div className="data-table-card" style={{ padding: '1.25rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Database size={18} className="text-primary" />
              <span style={{ fontWeight: 700, color: '#ffffff' }}>State Database</span>
            </div>
            <span className="status-pill status-pill-passed">CONNECTED</span>
          </div>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
            SQLite / PostgreSQL relational store for test executions, historical telemetry, and healed selectors.
          </p>
        </div>

        <div className="data-table-card" style={{ padding: '1.25rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Radio size={18} className="text-healed" />
              <span style={{ fontWeight: 700, color: '#ffffff' }}>Telemetry Stream (SSE)</span>
            </div>
            <span className="status-pill status-pill-passed">READY</span>
          </div>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
            Real-time Server-Sent Events stream delivering live agent state transitions and browser logs.
          </p>
        </div>
      </div>
    </div>
  );
}
