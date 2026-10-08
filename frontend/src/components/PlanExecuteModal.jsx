import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X, Play, Globe, Sparkles, AlertCircle, Loader2, CheckCircle2, Search } from 'lucide-react';
import { planAndExecuteWorkflow } from '../services/api';

const SAMPLE_PRESETS = [
  { name: 'Login Benchmark', url: 'https://the-internet.herokuapp.com/login', prompt: 'Verify user authentication form, test input selectors, and assert secure area state.' },
  { name: 'TodoMVC App', url: 'https://demo.playwright.dev/todomvc', prompt: 'Inspect interactive Todo application, check input field and item creation.' },
  { name: 'Hacker News', url: 'https://news.ycombinator.com', prompt: 'Verify live news feed, test search query input and navigation links.' },
  { name: 'Example Domain', url: 'https://example.com', prompt: 'Inspect domain landing page, assert heading and DOM structure.' },
];

export default function PlanExecuteModal({ isOpen, onClose, onExecutionStarted }) {
  const [appUrl, setAppUrl] = useState('https://the-internet.herokuapp.com/login');
  const [appName, setAppName] = useState('');
  const [testName, setTestName] = useState('');
  const [prompt, setPrompt] = useState('Inspect live website, discover interactive DOM elements, and autonomously verify page functionality.');
  const [headless, setHeadless] = useState(true);
  const [loading, setLoading] = useState(false);
  const [loadingStep, setLoadingStep] = useState('');
  const [error, setError] = useState(null);

  // Close on Escape & lock body scroll while modal is active
  useEffect(() => {
    if (!isOpen) return;
    function handleKeyDown(e) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', handleKeyDown);
    document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  function applyPreset(preset) {
    setAppUrl(preset.url);
    setPrompt(preset.prompt);
    setAppName('');
    setTestName('');
    setError(null);
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!appUrl.trim()) {
      setError('Please provide a valid website URL to analyze.');
      return;
    }

    setLoading(true);
    setError(null);
    setLoadingStep('Connecting to live website & scanning DOM...');

    try {
      const payload = {
        app_url: appUrl.trim(),
        app_name: appName.trim() || undefined,
        test_case_name: testName.trim() || undefined,
        prompt: prompt.trim() || undefined,
        headless: headless,
        // Notice: steps is NOT hardcoded! Backend will synthesize real steps from the live page elements.
      };

      setLoadingStep('Extracting interactive elements & generating test suite...');
      const result = await planAndExecuteWorkflow(payload);

      setLoadingStep('Execution complete! Loading live analysis...');
      if (onExecutionStarted) {
        onExecutionStarted(result);
      }
      setLoading(false);
      onClose();
    } catch (err) {
      console.error('Real QA analysis error:', err);
      setError(err.message || 'Failed to inspect website. Please verify the URL and backend status.');
      setLoading(false);
    }
  }

  const modalElement = (
    <div className="modal-overlay modal-backdrop" onClick={onClose} role="dialog" aria-modal="true">
      <div className="modal-content modal-card card-solid" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 640 }}>
        <div className="modal-header">
          <div className="modal-title-wrap modal-title-group">
            <div className="modal-badge">
              <Sparkles size={13} />
              <span>LIVE WEBSITE ANALYZER &amp; QA RUNNER</span>
            </div>
            <h3 className="modal-title">Analyze Real Website &amp; Execute Autonomous QA</h3>
            <p className="modal-subtitle">Enter any URL to extract real DOM elements, run quality audits, and execute tests</p>
          </div>
          <button className="modal-close-btn" onClick={onClose} aria-label="Close modal">
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="modal-form">
          {error && (
            <div className="modal-error-banner modal-alert alert-error" style={{ marginBottom: '1rem', padding: '0.75rem 1rem', background: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.3)', borderRadius: 8, color: '#f87171', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <AlertCircle size={16} />
              <span>{error}</span>
            </div>
          )}

          {/* Quick Presets */}
          <div className="form-group" style={{ marginBottom: '1rem' }}>
            <label className="form-label" style={{ fontSize: '0.8rem', color: '#94a3b8', display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.4rem' }}>
              <Search size={13} />
              <span>Quick Test Presets (Click to Load):</span>
            </label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
              {SAMPLE_PRESETS.map((p, idx) => (
                <button
                  type="button"
                  key={idx}
                  onClick={() => applyPreset(p)}
                  style={{
                    background: appUrl === p.url ? 'rgba(99, 102, 241, 0.25)' : 'rgba(30, 41, 59, 0.6)',
                    borderColor: appUrl === p.url ? '#6366f1' : 'rgba(148, 163, 184, 0.2)',
                    borderWidth: 1,
                    borderStyle: 'solid',
                    color: appUrl === p.url ? '#a5b4fc' : '#cbd5e1',
                    borderRadius: 6,
                    padding: '0.35rem 0.65rem',
                    fontSize: '0.75rem',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                  }}
                >
                  {p.name}
                </button>
              ))}
            </div>
          </div>

          {/* Target URL */}
          <div className="form-group" style={{ marginBottom: '1rem' }}>
            <label className="form-label" style={{ fontWeight: 600, color: '#f1f5f9' }}>
              Target Website URL <span style={{ color: '#f43f5e' }}>*</span>
            </label>
            <div className="input-with-icon" style={{ position: 'relative' }}>
              <Globe size={16} className="input-icon" style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: '#6366f1' }} />
              <input 
                type="url" 
                className="form-input with-icon" 
                value={appUrl}
                onChange={(e) => setAppUrl(e.target.value)}
                placeholder="https://your-website.com"
                required
                style={{ paddingLeft: '2.5rem', width: '100%', boxSizing: 'border-box' }}
              />
            </div>
            <p style={{ fontSize: '0.75rem', color: '#64748b', margin: '0.35rem 0 0 0' }}>
              TestSphere will connect live, inspect DOM buttons/inputs/forms, and run quality verification.
            </p>
          </div>

          {/* Optional App Name & Test Name */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginBottom: '1rem' }}>
            <div className="form-group" style={{ margin: 0 }}>
              <label className="form-label" style={{ fontSize: '0.8rem', color: '#cbd5e1' }}>App Label (Optional)</label>
              <input 
                type="text" 
                className="form-input" 
                value={appName}
                onChange={(e) => setAppName(e.target.value)}
                placeholder="Auto-detected from Page Title"
              />
            </div>
            <div className="form-group" style={{ margin: 0 }}>
              <label className="form-label" style={{ fontSize: '0.8rem', color: '#cbd5e1' }}>Test Name (Optional)</label>
              <input 
                type="text" 
                className="form-input" 
                value={testName}
                onChange={(e) => setTestName(e.target.value)}
                placeholder="Auto-generated from Goal"
              />
            </div>
          </div>

          {/* Testing Objective */}
          <div className="form-group" style={{ marginBottom: '1rem' }}>
            <label className="form-label" style={{ fontWeight: 600, color: '#f1f5f9' }}>
              QA Objective / Instructions (Optional Prompt)
            </label>
            <textarea 
              className="form-textarea" 
              rows={3}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="e.g. Verify login form, test search bar, check buttons, and assert page title..."
              style={{ width: '100%', boxSizing: 'border-box' }}
            />
          </div>

          <div className="form-checkbox-row" style={{ marginBottom: '1.25rem' }}>
            <label className="checkbox-label" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontSize: '0.82rem', color: '#94a3b8' }}>
              <input 
                type="checkbox" 
                checked={headless}
                onChange={(e) => setHeadless(e.target.checked)}
              />
              <span>Fast Cloud Execution Mode (Headless Browser / Live HTTP-DOM Inspection)</span>
            </label>
          </div>

          <div className="modal-footer" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid rgba(148, 163, 184, 0.15)', paddingTop: '1rem' }}>
            <button type="button" className="btn-secondary" onClick={onClose} disabled={loading}>
              Cancel
            </button>
            <button type="submit" className="btn-primary" disabled={loading} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: '#6366f1', color: 'white', padding: '0.65rem 1.25rem', borderRadius: 8, fontWeight: 600, cursor: 'pointer' }}>
              {loading ? (
                <>
                  <Loader2 size={16} className="spin-icon" />
                  <span>{loadingStep || 'Analyzing Website...'}</span>
                </>
              ) : (
                <>
                  <Play size={16} />
                  <span>Inspect &amp; Run Autonomous QA</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );

  return typeof document !== 'undefined' ? createPortal(modalElement, document.body) : modalElement;
}
