import React, { useEffect, useRef } from 'react';
import { Play, Pause, RotateCcw, Clock } from 'lucide-react';
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

  return (
    <section className="execution-grid">
      {/* Left: Live Execution Card */}
      <div className="live-execution-card">
        <div className="live-card-header">
          <div className="live-title-area">
            <h3>Live Test Execution</h3>
            <span className="live-status-pill">
              <span className="dot-indicator passed" style={{ width: 8, height: 8 }}></span>
              <span>Running Simulation</span>
            </span>
          </div>

          <div className="live-actions-area">
            <span className="exec-id-tag mono" id="current-exec-id">
              {activeRun?.id || 'TC_LOGIN_001'}
            </span>
            <div className="live-timer-badge">
              <Clock size={14} style={{ color: '#38bdf8' }} />
              <span id="execution-timer">{formatTime(timerSeconds)}</span>
            </div>
            <button 
              className="btn-stop" 
              id="btn-toggle-execution"
              onClick={onTogglePlay}
              title={isRunning ? 'Pause simulation' : 'Resume simulation'}
            >
              {isRunning ? <Pause size={14} /> : <Play size={14} />}
              <span>{isRunning ? 'Pause' : 'Resume'}</span>
            </button>
            <button 
              className="btn-stop" 
              onClick={onReset}
              title="Rerun test"
              style={{ background: 'rgba(56, 189, 248, 0.15)', borderColor: 'rgba(56, 189, 248, 0.4)', color: '#38bdf8' }}
            >
              <RotateCcw size={14} />
            </button>
          </div>
        </div>

        {/* 6-Stage Autonomous Pipeline Stepper */}
        <PipelineStepper 
          currentStepIndex={currentStepIndex} 
          onStepClick={onStepClick} 
        />

        {/* Live Terminal Window */}
        <div className="terminal-window" id="terminal-logs" ref={terminalRef}>
          {logs.map((log, idx) => (
            <div className="log-line" key={idx}>
              <span className="log-time">[{log.time || '10:24:00'}]</span>
              <span className={`log-text ${log.type || 'default'}`}>{log.text}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Right Column: Diagnostics (Failure Analysis & Healing Solution) */}
      <div className="diagnostics-col">
        <DiagnosticsPanel 
          failureData={activeRun?.failure}
          healingData={activeRun?.healing}
          outcome={activeRun?.outcome}
        />
      </div>
    </section>
  );
}
