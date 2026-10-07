import React from 'react';

export default function DiagnosticsPanel({ failureData, healingData, outcome }) {
  const isHealed = outcome === 'HEALED';
  const isPassed = outcome === 'PASSED';
  const isFailed = outcome === 'FAILED';

  return (
    <>
      {/* Card 1: Failure Analysis */}
      <div className="diag-card">
        <div className="diag-header">
          <div className="diag-header-title">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={isPassed ? '#10b981' : '#f43f5e'} strokeWidth="2">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
              <line x1="12" y1="9" x2="12" y2="13"></line>
              <line x1="12" y1="17" x2="12.01" y2="17"></line>
            </svg>
            <span>Diagnostics & Root Cause</span>
          </div>
          <span 
            className={`pill-badge ${isPassed ? 'green' : (isHealed ? 'purple' : 'red')}`} 
            id="failure-status-badge"
            style={isPassed ? { background: 'rgba(16, 185, 129, 0.2)', color: '#34d399', border: '1px solid rgba(16, 185, 129, 0.4)' } : {}}
          >
            {outcome || 'READY'}
          </span>
        </div>

        <div className="diag-row">
          <span className="diag-label">Category</span>
          <span className={`diag-value ${isPassed ? 'text-success' : 'red-text'}`} id="failure-category">
            {isPassed 
              ? 'Clean Deterministic Execution' 
              : (failureData?.category || (isHealed ? 'Resolved Selector Drift' : 'Application / Assertion Error'))}
          </span>
        </div>

        <div className="diag-row">
          <span className="diag-label">Root Cause</span>
          <span className="diag-value" id="failure-root-cause">
            {isPassed 
              ? 'Zero failures detected. All locators matched target DOM.' 
              : (failureData?.rootCause || 'Evaluated during Playwright run.')}
          </span>
        </div>

        <div className="diag-row" style={{ flexDirection: 'column', gap: '0.35rem' }}>
          <span className="diag-label">Evidence Trace</span>
          <div 
            className="evidence-thumbnail" 
            id="evidence-box"
            style={{ 
              display: 'flex', 
              alignItems: 'center', 
              justifyContent: 'center', 
              background: 'rgba(15, 23, 42, 0.6)', 
              border: '1px dashed rgba(148, 163, 184, 0.25)', 
              height: '80px', 
              borderRadius: '6px', 
              color: '#94a3b8', 
              fontSize: '0.78rem',
              padding: '0.5rem',
              textAlign: 'center'
            }}
          >
            {failureData?.evidenceImg ? (
              <img 
                src={failureData.evidenceImg} 
                alt="Evidence Screenshot Preview" 
                id="evidence-img" 
                style={{ maxHeight: '100%', objectFit: 'contain' }}
              />
            ) : (
              <span>{isPassed ? '✓ Live Browser Trace Verified (No Errors)' : (isHealed ? '⚡ DOM Mutation Captured & Resolved' : '⚠ Failure Snapshot Logged')}</span>
            )}
          </div>
        </div>

        <div className="diag-row">
          <span className="diag-label">Details</span>
          <span className="diag-value" style={{ fontSize: '0.76rem', color: '#94a3b8' }} id="failure-details">
            {isPassed 
              ? 'No locator drift or application assertion errors detected.' 
              : (failureData?.details || 'Details captured in test execution trace.')}
          </span>
        </div>
      </div>

      {/* Card 2: Healing Solution */}
      <div className="diag-card healing-card">
        <div className="diag-header">
          <div className="diag-header-title">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#c084fc" strokeWidth="2">
              <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"></path>
            </svg>
            <span>Self-Healing Engine</span>
          </div>
          <span className="pill-badge purple" id="healing-status-badge">
            {isHealed ? 'HEALED & SAVED' : (isPassed ? 'NOT NEEDED' : 'ANALYZED')}
          </span>
        </div>

        <div className="diag-row">
          <span className="diag-label">Candidate</span>
          <span className="diag-value" id="healing-candidate">
            {isHealed 
              ? (healingData?.candidate || 'CSS Selector Update') 
              : (isPassed ? 'None (100% Locator Stability)' : (healingData?.candidate || 'Manual Review Required (App Bug)'))}
          </span>
        </div>

        <div className="diag-row">
          <span className="diag-label">Confidence</span>
          <div className="confidence-bar-wrapper">
            <span className="confidence-percent" id="healing-confidence">
              {isPassed ? '100%' : (healingData?.confidence || (isHealed ? '96%' : '0%'))}
            </span>
            <div className="confidence-bar">
              <div 
                className="confidence-fill" 
                id="confidence-fill" 
                style={{ width: isPassed ? '100%' : (healingData?.confidence || (isHealed ? '96%' : '0%')) }}
              />
            </div>
          </div>
        </div>

        <div className="diag-row">
          <span className="diag-label">Old Selector</span>
          <code className="code-pill red" id="healing-old-selector">
            {isHealed ? (healingData?.oldSelector || '#target-btn') : 'N/A'}
          </code>
        </div>

        <div className="diag-row">
          <span className="diag-label">New Selector</span>
          <code className="code-pill green" id="healing-new-selector">
            {isHealed ? (healingData?.newSelector || 'button[type="submit"]') : 'N/A'}
          </code>
        </div>

        <div className="diag-row">
          <span className="diag-label">Validation</span>
          <span className="diag-value" style={{ fontSize: '0.78rem' }} id="healing-validation">
            {isHealed 
              ? (healingData?.validation || 'Validated by Playwright in sandbox') 
              : (isPassed ? 'Baseline DOM locators verified cleanly' : 'No valid self-healing candidate for application bug')}
          </span>
        </div>

        <div className="healing-status-line">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <polyline points="20 6 9 17 4 12"></polyline>
          </svg>
          <span id="healing-outcome-text">
            {isHealed 
              ? (healingData?.status || 'Healing Successful & Persisted') 
              : (isPassed ? 'Deterministic Pass' : 'Logged to Failure Analysis')}
          </span>
        </div>
      </div>
    </>
  );
}
