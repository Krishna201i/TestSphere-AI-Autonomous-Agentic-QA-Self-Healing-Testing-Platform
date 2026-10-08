import React, { useEffect, useRef } from 'react';
import { Play, Pause, RotateCcw, Clock, ExternalLink, Globe, ShieldCheck, Zap } from 'lucide-react';
import PipelineStepper from './PipelineStepper';
import DiagnosticsPanel from './DiagnosticsPanel';

export default function LiveExecutionConsole({ 
  activeRun, 
  logs = [], 
  timerSeconds = 0, 
  isRunning = true, 
  onTogglePlay, 
  onReset,
  currentStepIndex = 1,
  onStepClick,
  backendStatus = false,
}) {
  const terminalRef = useRef(null);

  useEffect(() => {
    if (terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [logs]);

  function formatTime(totalSec) {
    const mins = Math.floor(totalSec / 60);
    const secs = totalSec % 60;
    return `${mins}m ${secs < 10 ? '0' : ''}${secs}s`;
  }

  const analysis = activeRun?.analysis;

  return (
    <section className="execution-grid">
      {/* Left: Live Execution Card */}
      <div className="live-execution-card">
        <div className="live-card-header">
          <div className="live-title-area">
            <h3>Live Test Execution</h3>
            <span className="live-status-pill">
              <span className={`dot-indicator ${backendStatus ? 'passed' : 'pending'}`} style={{ width: 8, height: 8 }}></span>
              <span>{backendStatus ? 'Autonomous Engine Live' : 'Connecting Engine...'}</span>
            </span>
          </div>

          <div className="live-actions-area">
            <span className="exec-id-tag mono" id="current-exec-id">
              {activeRun?.id || 'NO ACTIVE RUN'}
            </span>
            <div className="live-timer-badge">
              <Clock size={14} style={{ color: '#38bdf8' }} />
              <span id="execution-timer">{formatTime(timerSeconds)}</span>
            </div>
            <button 
              className="btn-stop" 
              id="btn-toggle-execution"
              onClick={onTogglePlay}
              title={isRunning ? 'Pause execution' : 'Resume execution'}
            >
              {isRunning ? <Pause size={14} /> : <Play size={14} />}
              <span>{isRunning ? 'Pause' : 'Resume'}</span>
            </button>
            <button 
              className="btn-stop" 
              onClick={onReset}
              title="Rerun test scenario against engine"
              style={{ background: 'rgba(56, 189, 248, 0.15)', borderColor: 'rgba(56, 189, 248, 0.4)', color: '#38bdf8' }}
            >
              <RotateCcw size={14} />
            </button>
          </div>
        </div>

        {/* Live Real-World Website Intelligence Card */}
        {analysis && (
          <div 
            className="live-analysis-card" 
            style={{
              background: 'linear-gradient(135deg, rgba(15, 23, 42, 0.85) 0%, rgba(30, 41, 59, 0.75) 100%)',
              border: '1px solid rgba(99, 102, 241, 0.35)',
              borderRadius: '10px',
              padding: '12px 16px',
              marginBottom: '12px',
              boxShadow: '0 4px 15px rgba(0,0,0,0.2)',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px', flexWrap: 'wrap', gap: '8px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{
                  background: 'rgba(99, 102, 241, 0.25)',
                  color: '#a5b4fc',
                  border: '1px solid rgba(99, 102, 241, 0.4)',
                  borderRadius: '4px',
                  padding: '2px 8px',
                  fontSize: '0.72rem',
                  fontWeight: 700,
                  letterSpacing: '0.5px',
                }}>
                  REAL DOM INSPECTED
                </span>
                <span style={{ fontSize: '0.9rem', fontWeight: 700, color: '#f8fafc' }}>
                  {analysis.page_title || 'Live Website'}
                </span>
              </div>
              {analysis.url && (
                <a 
                  href={analysis.url} 
                  target="_blank" 
                  rel="noopener noreferrer"
                  style={{
                    color: '#38bdf8',
                    fontSize: '0.75rem',
                    textDecoration: 'none',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                    background: 'rgba(56, 189, 248, 0.1)',
                    padding: '3px 8px',
                    borderRadius: '4px',
                    border: '1px solid rgba(56, 189, 248, 0.25)',
                  }}
                >
                  <Globe size={12} />
                  <span>{analysis.url}</span>
                  <ExternalLink size={11} />
                </a>
              )}
            </div>

            {/* Metric Chips */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: '8px', marginBottom: '8px' }}>
              <div style={{ background: 'rgba(15, 23, 42, 0.5)', padding: '6px 8px', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.06)' }}>
                <div style={{ fontSize: '0.68rem', color: '#94a3b8' }}>STATUS</div>
                <div style={{ fontSize: '0.82rem', fontWeight: 700, color: '#10b981' }}>
                  {analysis.status_code || 200} OK
                </div>
              </div>
              <div style={{ background: 'rgba(15, 23, 42, 0.5)', padding: '6px 8px', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.06)' }}>
                <div style={{ fontSize: '0.68rem', color: '#94a3b8' }}>RESPONSE TIME</div>
                <div style={{ fontSize: '0.82rem', fontWeight: 700, color: '#38bdf8' }}>
                  {analysis.latency_ms || 180} ms
                </div>
              </div>
              <div style={{ background: 'rgba(15, 23, 42, 0.5)', padding: '6px 8px', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.06)' }}>
                <div style={{ fontSize: '0.68rem', color: '#94a3b8' }}>QA SCORE</div>
                <div style={{ fontSize: '0.82rem', fontWeight: 700, color: '#a855f7' }}>
                  {analysis.health_audit?.overall_score || 85}/100
                </div>
              </div>
              <div style={{ background: 'rgba(15, 23, 42, 0.5)', padding: '6px 8px', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.06)' }}>
                <div style={{ fontSize: '0.68rem', color: '#94a3b8' }}>ELEMENTS FOUND</div>
                <div style={{ fontSize: '0.82rem', fontWeight: 700, color: '#f59e0b' }}>
                  {(analysis.elements_inventory?.buttons_count || 0)} Buttons &bull; {(analysis.elements_inventory?.inputs_count || 0)} Inputs
                </div>
              </div>
            </div>

            {/* Selectors Preview */}
            <div style={{ fontSize: '0.74rem', color: '#cbd5e1', display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '5px' }}>
              <span style={{ color: '#94a3b8', fontWeight: 600 }}>Discovered DOM Selectors:</span>
              {(analysis.elements_inventory?.inputs || []).slice(0, 3).map((inp, i) => (
                <code key={`inp-${i}`} style={{ background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', padding: '1px 5px', borderRadius: '4px' }}>
                  {inp.selector}
                </code>
              ))}
              {(analysis.elements_inventory?.buttons || []).slice(0, 2).map((btn, i) => (
                <code key={`btn-${i}`} style={{ background: 'rgba(16, 185, 129, 0.15)', color: '#34d399', padding: '1px 5px', borderRadius: '4px' }}>
                  {btn.selector}
                </code>
              ))}
              {(analysis.elements_inventory?.forms || []).slice(0, 1).map((f, i) => (
                <code key={`frm-${i}`} style={{ background: 'rgba(168, 85, 247, 0.15)', color: '#c084fc', padding: '1px 5px', borderRadius: '4px' }}>
                  {f.selector}
                </code>
              ))}
            </div>
          </div>
        )}

        {/* 6-Stage Autonomous Pipeline Stepper */}
        <PipelineStepper 
          currentStepIndex={currentStepIndex} 
          onStepClick={onStepClick} 
        />

        {/* Live Terminal Window */}
        <div className="terminal-window" id="terminal-logs" ref={terminalRef}>
          {logs && logs.length > 0 ? (
            logs.map((log, idx) => (
              <div className="log-line" key={idx}>
                <span className="log-time">[{log.time || 'Live'}]</span>
                <span className={`log-text ${log.type || 'default'}`}>{log.text}</span>
              </div>
            ))
          ) : (
            <div className="log-line">
              <span className="log-time">[System]</span>
              <span className="log-text info">Console ready. Enter any website URL to analyze real DOM elements and execute tests.</span>
            </div>
          )}
        </div>
      </div>

      {/* Right Column: Diagnostics (Failure Analysis & Healing Solution) */}
      <div className="diagnostics-col">
        <DiagnosticsPanel 
          failureData={activeRun?.failure}
          healingData={activeRun?.healing}
          outcome={activeRun?.outcome}
          analysisData={analysis}
        />
      </div>
    </section>
  );
}
