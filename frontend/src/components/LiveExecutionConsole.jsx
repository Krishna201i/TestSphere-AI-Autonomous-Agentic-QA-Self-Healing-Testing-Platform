import React, { useState, useEffect, useRef } from 'react';
import { 
  Play, 
  Pause, 
  RotateCcw, 
  Terminal, 
  Clock, 
  ShieldCheck, 
  Sparkles,
  Download,
  Filter
} from 'lucide-react';
import DiagnosticsPanel from './DiagnosticsPanel';

export default function LiveExecutionConsole({ 
  activeRun, 
  logs, 
  timerSeconds, 
  isRunning, 
  onTogglePlay, 
  onReset 
}) {
  const [filterType, setFilterType] = useState('all');
  const logContainerRef = useRef(null);

  // Auto scroll logs
  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs]);

  function formatTime(totalSec) {
    const mins = Math.floor(totalSec / 60);
    const secs = totalSec % 60;
    return `${mins}m ${secs < 10 ? '0' : ''}${secs}s`;
  }

  const filteredLogs = logs.filter(log => {
    if (filterType === 'all') return true;
    if (filterType === 'info') return log.type === 'info' || log.type === 'default';
    if (filterType === 'warn') return log.type === 'warn';
    if (filterType === 'error') return log.type === 'error';
    if (filterType === 'agent') return log.type === 'agent' || log.type === 'success';
    return true;
  });

  return (
    <div className="live-console-grid">
      {/* Left Column: Live Terminal Stream */}
      <div className="terminal-panel card-glass">
        <div className="terminal-header">
          <div className="terminal-meta-left">
            <div className="terminal-title">
              <Terminal size={17} className="text-cyan" />
              <span>Live Telemetry & Execution Log</span>
            </div>
            <div className="terminal-run-id">
              <span className="mono">{activeRun?.id || 'TC_LOGIN_001'}</span>
              <span className="run-name">• {activeRun?.name || 'User Login Flow'}</span>
            </div>
          </div>

          <div className="terminal-controls-right">
            <div className="elapsed-timer-badge">
              <Clock size={14} />
              <span id="execution-timer">{formatTime(timerSeconds)}</span>
            </div>

            <button 
              className={`control-btn ${isRunning ? 'pause' : 'resume'}`}
              onClick={onTogglePlay}
              title={isRunning ? 'Pause Simulation' : 'Resume Simulation'}
            >
              {isRunning ? <Pause size={14} /> : <Play size={14} />}
              <span>{isRunning ? 'Pause' : 'Resume'}</span>
            </button>

            <button className="control-icon-btn" onClick={onReset} title="Rerun Simulation">
              <RotateCcw size={14} />
            </button>
          </div>
        </div>

        {/* Filter Bar */}
        <div className="terminal-filter-bar">
          <div className="filter-group">
            <button 
              className={`filter-pill ${filterType === 'all' ? 'active' : ''}`}
              onClick={() => setFilterType('all')}
            >
              All Events ({logs.length})
            </button>
            <button 
              className={`filter-pill ${filterType === 'info' ? 'active' : ''}`}
              onClick={() => setFilterType('info')}
            >
              Info
            </button>
            <button 
              className={`filter-pill ${filterType === 'warn' ? 'active' : ''}`}
              onClick={() => setFilterType('warn')}
            >
              Warnings
            </button>
            <button 
              className={`filter-pill ${filterType === 'error' ? 'active' : ''}`}
              onClick={() => setFilterType('error')}
            >
              Errors
            </button>
            <button 
              className={`filter-pill ${filterType === 'agent' ? 'active' : ''}`}
              onClick={() => setFilterType('agent')}
            >
              AI Agents
            </button>
          </div>

          <div className="filter-status">
            <span className="status-pill healed">
              <Sparkles size={13} />
              <span>{activeRun?.outcome || 'HEALED'}</span>
            </span>
          </div>
        </div>

        {/* Scrollable Logs Output */}
        <div className="terminal-body" ref={logContainerRef} id="logs-terminal">
          {filteredLogs.map((item, idx) => (
            <div key={idx} className={`log-entry log-${item.type || 'default'}`}>
              <span className="log-time mono">{item.time || '10:24:00'}</span>
              <span className={`log-badge badge-${item.type || 'default'}`}>
                {(item.type || 'INFO').toUpperCase()}
              </span>
              <span className="log-msg mono">{item.text}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Right Column: AI Diagnostics & Self-Healing Cards */}
      <DiagnosticsPanel 
        failureData={activeRun?.failure}
        healingData={activeRun?.healing}
        outcome={activeRun?.outcome}
      />
    </div>
  );
}
