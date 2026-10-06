import React from 'react';
import { AlertTriangle, Sparkles, CheckCircle2, XCircle, Eye, ArrowRight } from 'lucide-react';

export default function DiagnosticsPanel({ failureData, healingData, outcome }) {
  const isHealed = outcome === 'HEALED' || outcome === 'PASSED';

  return (
    <div className="diagnostics-column">
      {/* Failure Analysis Card */}
      <div className="diag-card failure-card card-glass">
        <div className="card-top">
          <div className="card-title-group">
            <AlertTriangle size={18} className="text-rose" />
            <span className="card-heading">AI Failure Analysis</span>
          </div>
          <span className={`pill-badge ${failureData?.category === 'None' ? 'green' : 'red'}`} id="failure-status-badge">
            {outcome || 'FAILED'}
          </span>
        </div>

        <div className="diag-content">
          <div className="diag-row">
            <span className="row-label">Category:</span>
            <span className="row-value highlight-rose" id="failure-category">
              {failureData?.category || 'Element Not Found (Locator Changed)'}
            </span>
          </div>

          <div className="diag-row">
            <span className="row-label">Root Cause:</span>
            <span className="row-value" id="failure-root-cause">
              {failureData?.rootCause || 'Target selector `#login-btn` timed out in DOM'}
            </span>
          </div>

          <div className="diag-row">
            <span className="row-label">Details:</span>
            <p className="row-details-text" id="failure-details">
              {failureData?.details || 'Playwright engine timed out after 5000ms waiting for `#login-btn`. Triggered FailureAnalyzerAgent.'}
            </p>
          </div>

          {/* Screenshot Evidence */}
          <div className="evidence-preview-wrap">
            <div className="evidence-header">
              <span className="evidence-label">Visual Failure Evidence</span>
              <span className="evidence-zoom">
                <Eye size={13} /> Inspect Frame
              </span>
            </div>
            <div className="evidence-img-container">
              <img 
                src={failureData?.evidenceImg || '/assets/evidence_preview.jpg'} 
                alt="Failure Screenshot" 
                className="evidence-screenshot"
                onError={(e) => {
                  e.target.style.display = 'none';
                }}
              />
              <div className="evidence-overlay">
                <span className="evidence-tag">Step #1 Failure Captured</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Self-Healing Card */}
      <div className="diag-card healing-card card-glass">
        <div className="card-top">
          <div className="card-title-group">
            <Sparkles size={18} className="text-purple" />
            <span className="card-heading">Autonomous Self-Healing</span>
          </div>
          <span className="pill-badge purple">
            {isHealed ? 'Healing Verified' : 'AI Analysis'}
          </span>
        </div>

        <div className="diag-content">
          <div className="confidence-meter-wrap">
            <div className="confidence-meta">
              <span className="confidence-label">AI Confidence Score</span>
              <span className="confidence-score" id="healing-confidence">
                {healingData?.confidence || '92%'}
              </span>
            </div>
            <div className="progress-bar-bg">
              <div 
                className="progress-bar-fill" 
                id="confidence-fill" 
                style={{ width: healingData?.confidence || '92%' }}
              />
            </div>
          </div>

          <div className="selector-diff-box">
            <div className="diff-item old-selector">
              <div className="diff-tag">Original Locator:</div>
              <code className="mono text-rose" id="healing-old-selector">
                {healingData?.oldSelector || '#login-btn'}
              </code>
            </div>

            <div className="diff-arrow">
              <ArrowRight size={16} />
            </div>

            <div className="diff-item new-selector">
              <div className="diff-tag">Healed Candidate:</div>
              <code className="mono text-emerald" id="healing-new-selector">
                {healingData?.newSelector || 'button[type="submit"]'}
              </code>
            </div>
          </div>

          <div className="validation-status-box">
            <div className="val-icon-wrap">
              {isHealed ? (
                <CheckCircle2 size={16} className="text-emerald" />
              ) : (
                <XCircle size={16} className="text-rose" />
              )}
            </div>
            <div className="val-text">
              <span className="val-title" id="healing-validation">
                {healingData?.validation || 'Successfully Validated by Engine'}
              </span>
              <span className="val-subtitle" id="healing-outcome-text">
                {healingData?.status || 'Replacement selector passed browser assertion'}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
