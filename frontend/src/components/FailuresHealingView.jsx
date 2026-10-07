import React, { useState } from 'react';
import { 
  ShieldAlert, 
  Wrench, 
  CheckCircle2, 
  AlertTriangle, 
  Code, 
  Sparkles, 
  ArrowRight, 
  ExternalLink, 
  Eye, 
  Layers, 
  Cpu,
  XCircle,
  Clock
} from 'lucide-react';

const HEALED_RECORDS = [
  {
    id: 'HEAL_001',
    testCaseId: 'TC_LOGIN_001',
    testName: 'User Login & Auth Flow',
    timestamp: 'Today at 10:24 AM',
    driftType: 'CSS Selector Changed',
    confidence: '92%',
    oldSelector: '#login-btn',
    newSelector: 'button[type="submit"]',
    rootCause: "Element with selector '#login-btn' was renamed during staging deployment. Found semantic replacement button with type submit.",
    agentProof: 'Playwright engine tested candidate in isolated context: returned single interactive DOM element. Assertions passed.',
    status: 'HEALED & PERSISTED',
    evidenceImg: '/assets/evidence_preview.jpg'
  },
  {
    id: 'HEAL_002',
    testCaseId: 'TC_CHECKOUT_003',
    testName: 'Payment Submission Button',
    timestamp: 'Today at 09:58 AM',
    driftType: 'Dynamic ID Drift',
    confidence: '95%',
    oldSelector: '#checkout-step-btn-4829',
    newSelector: 'button[data-testid="complete-checkout"]',
    rootCause: 'Dynamic UUID suffix in button id changed on reload. Self-healing analyzer selected resilient data-testid attribute.',
    agentProof: 'Verified unique locator across 3 viewport sizes in Playwright Chromium. Zero ambiguity.',
    status: 'HEALED & PERSISTED',
    evidenceImg: '/assets/evidence_preview.jpg'
  },
  {
    id: 'HEAL_003',
    testCaseId: 'TC_PROFILE_005',
    testName: 'Avatar Upload Input',
    timestamp: 'Today at 09:12 AM',
    driftType: 'DOM Structural Shift',
    confidence: '88%',
    oldSelector: 'div.upload-box > input',
    newSelector: 'input[type="file"][name="avatar"]',
    rootCause: 'Modal DOM wrapper refactored into a custom Web Component. Re-targeted input by name and type.',
    agentProof: 'Playwright file-upload action succeeded without timeout.',
    status: 'HEALED & PERSISTED',
    evidenceImg: '/assets/evidence_preview.jpg'
  },
  {
    id: 'HEAL_004',
    testCaseId: 'TC_SEARCH_007',
    testName: 'Filter Dropdown Option',
    timestamp: 'Yesterday at 04:30 PM',
    driftType: 'Text Heuristic Mutation',
    confidence: '91%',
    oldSelector: 'text="All Categories"',
    newSelector: 'select[name="category"] option[value="all"]',
    rootCause: 'UI localization changed label text from "All Categories" to "Browse All". Recovered via value attribute.',
    agentProof: 'Selector triggered select_option action cleanly.',
    status: 'HEALED & PERSISTED',
    evidenceImg: '/assets/evidence_preview.jpg'
  }
];

export default function FailuresHealingView({ onOpenPlanModal }) {
  const [activeTab, setActiveTab] = useState('ALL');
  const [selectedRecord, setSelectedRecord] = useState(HEALED_RECORDS[0]);

  return (
    <div className="view-container">
      {/* Title Header */}
      <div className="page-title-row">
        <div className="page-title-box">
          <div className="page-icon-badge" style={{ background: 'linear-gradient(135deg, rgba(168, 85, 247, 0.3), rgba(236, 72, 153, 0.3))' }}>
            <ShieldAlert size={22} color="#c084fc" />
          </div>
          <div>
            <h2>Failures & Self-Healing Hub</h2>
            <p>AI agent diagnostics, locator drift resolution, and autonomous selector repair pipeline</p>
          </div>
        </div>

        <button 
          className="btn-run-small"
          onClick={onOpenPlanModal}
          style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', cursor: 'pointer' }}
        >
          <Sparkles size={15} />
          <span>+ Trigger Healing Test</span>
        </button>
      </div>

      {/* KPI Overview Cards */}
      <div className="kpi-grid">
        <div className="kpi-card">
          <div className="kpi-label">Auto-Healed Locators</div>
          <div className="kpi-value text-healed">86</div>
          <div className="kpi-footer text-healed">Zero Pipeline Downtime</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Healing Success Rate</div>
          <div className="kpi-value text-success">92.4%</div>
          <div className="kpi-footer text-success">High Confidence Score</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Average Time to Heal</div>
          <div className="kpi-value text-cyan">1.8s</div>
          <div className="kpi-footer text-cyan">In-Memory Engine</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">True App Regressions</div>
          <div className="kpi-value text-danger">24</div>
          <div className="kpi-footer text-danger">Reported as Bugs</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Flakiness Eliminated</div>
          <div className="kpi-value">98%</div>
          <div className="kpi-footer text-primary">Self-Healing Protected</div>
        </div>
      </div>

      {/* Main 2-Column Split View: List on Left, Deep Dive on Right */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.35fr', gap: '1.5rem', alignItems: 'start' }}>
        {/* Left Column: Healing Records List */}
        <div className="data-table-card" style={{ padding: '1rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          <div style={{ fontSize: '0.88rem', fontWeight: 700, color: '#ffffff', display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
            <Wrench size={16} className="text-healed" />
            <span>Autonomous Healing Audit Trail</span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
            {HEALED_RECORDS.map((record) => {
              const isSelected = selectedRecord?.id === record.id;
              return (
                <div 
                  key={record.id}
                  onClick={() => setSelectedRecord(record)}
                  className={`nav-item ${isSelected ? 'active' : ''}`}
                  style={{
                    padding: '0.9rem',
                    borderRadius: 'var(--radius-md)',
                    border: isSelected ? '1px solid rgba(168, 85, 247, 0.6)' : '1px solid var(--border-subtle)',
                    background: isSelected ? 'rgba(168, 85, 247, 0.12)' : 'rgba(16, 26, 48, 0.5)',
                    cursor: 'pointer',
                    transition: 'all 0.2s ease',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '0.45rem'
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: 600, color: '#ffffff', fontSize: '0.88rem' }}>{record.testName}</span>
                    <span className="status-pill status-pill-healed" style={{ fontSize: '0.72rem' }}>
                      {record.confidence}
                    </span>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', fontSize: '0.76rem', color: 'var(--text-muted)' }}>
                    <span className="mono">{record.testCaseId}</span>
                    <span>•</span>
                    <span>{record.driftType}</span>
                    <span>•</span>
                    <span>{record.timestamp}</span>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.25rem' }}>
                    <span className="mono" style={{ fontSize: '0.75rem', color: '#fb7185', background: 'rgba(244, 63, 94, 0.1)', padding: '0.1rem 0.4rem', borderRadius: '4px' }}>
                      {record.oldSelector}
                    </span>
                    <ArrowRight size={12} color="var(--text-muted)" />
                    <span className="mono" style={{ fontSize: '0.75rem', color: '#34d399', background: 'rgba(16, 185, 129, 0.1)', padding: '0.1rem 0.4rem', borderRadius: '4px' }}>
                      {record.newSelector}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right Column: Deep Inspector */}
        {selectedRecord && (
          <div className="data-table-card" style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', borderBottom: '1px solid rgba(38, 56, 89, 0.5)', paddingBottom: '1rem' }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <Sparkles size={18} className="text-healed" />
                  <h3 style={{ fontSize: '1.15rem', fontWeight: 700, color: '#ffffff' }}>{selectedRecord.testName}</h3>
                </div>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
                  {selectedRecord.testCaseId} • Identified by FailureAnalyzer Agent
                </div>
              </div>

              <span className="status-pill status-pill-healed">
                <CheckCircle2 size={13} />
                <span>{selectedRecord.status}</span>
              </span>
            </div>

            {/* Selector Comparison Banner */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
              <div style={{ background: 'rgba(244, 63, 94, 0.08)', border: '1px solid rgba(244, 63, 94, 0.3)', borderRadius: 'var(--radius-md)', padding: '1rem' }}>
                <div style={{ fontSize: '0.72rem', fontWeight: 700, color: '#fb7185', letterSpacing: '0.05em' }}>
                  ORIGINAL BROKEN SELECTOR
                </div>
                <div className="mono" style={{ fontSize: '0.88rem', color: '#ffffff', marginTop: '0.4rem', fontWeight: 600 }}>
                  {selectedRecord.oldSelector}
                </div>
                <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', marginTop: '0.35rem' }}>
                  Result: Timeout (DOM node absent)
                </div>
              </div>

              <div style={{ background: 'rgba(16, 185, 129, 0.08)', border: '1px solid rgba(16, 185, 129, 0.3)', borderRadius: 'var(--radius-md)', padding: '1rem' }}>
                <div style={{ fontSize: '0.72rem', fontWeight: 700, color: '#34d399', letterSpacing: '0.05em', display: 'flex', justifyContent: 'space-between' }}>
                  <span>AI SYNTHESIZED REPLACEMENT</span>
                  <span style={{ color: '#c084fc' }}>Confidence: {selectedRecord.confidence}</span>
                </div>
                <div className="mono" style={{ fontSize: '0.88rem', color: '#ffffff', marginTop: '0.4rem', fontWeight: 600 }}>
                  {selectedRecord.newSelector}
                </div>
                <div style={{ fontSize: '0.76rem', color: '#34d399', marginTop: '0.35rem' }}>
                  Verified: Single unique interactive target
                </div>
              </div>
            </div>

            {/* AI Agent Root Cause Analysis */}
            <div style={{ background: 'rgba(16, 26, 48, 0.6)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', padding: '1rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <div style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                <Cpu size={15} className="text-cyan" />
                <span>AI Root Cause Diagnosis</span>
              </div>
              <p style={{ fontSize: '0.85rem', color: '#e2e8f0', lineHeight: 1.5 }}>
                {selectedRecord.rootCause}
              </p>
            </div>

            {/* Engine Verification Proof */}
            <div style={{ background: 'rgba(16, 26, 48, 0.6)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', padding: '1rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <div style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                <CheckCircle2 size={15} className="text-success" />
                <span>Playwright Isolated Verification Proof</span>
              </div>
              <p style={{ fontSize: '0.85rem', color: '#e2e8f0', lineHeight: 1.5 }}>
                {selectedRecord.agentProof}
              </p>
            </div>

            {/* Visual Evidence Preview */}
            <div>
              <div style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                <Eye size={15} />
                <span>DOM Snapshot & Visual Evidence</span>
              </div>
              <div style={{ borderRadius: 'var(--radius-md)', overflow: 'hidden', border: '1px solid var(--border-subtle)', background: '#000000', maxHeight: '180px', display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
                <img 
                  src={selectedRecord.evidenceImg} 
                  alt="DOM Evidence snapshot"
                  style={{ width: '100%', height: 'auto', objectFit: 'cover' }}
                />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
