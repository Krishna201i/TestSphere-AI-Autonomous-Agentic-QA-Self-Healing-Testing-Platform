import React, { useState, useEffect } from 'react';
import { Search, Clock, Plus, Zap, CheckCircle2, AlertCircle } from 'lucide-react';

export default function Header({ searchQuery, setSearchQuery, onNewRunClick, backendStatus }) {
  const [clockStr, setClockStr] = useState('');

  useEffect(() => {
    function updateTime() {
      const now = new Date();
      const options = { weekday: 'short', month: 'short', day: 'numeric' };
      const datePart = now.toLocaleDateString('en-US', options);
      const timePart = now.toLocaleTimeString('en-US', { hour12: true });
      setClockStr(`${datePart} • ${timePart}`);
    }
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header className="top-header">
      <div className="header-left">
        <div className="search-bar">
          <Search size={16} className="search-icon" />
          <input
            type="text"
            id="global-search"
            placeholder="Search test cases, selectors, logs..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          <span className="search-shortcut">⌘K</span>
        </div>
      </div>

      <div className="header-right">
        <div className="header-clock">
          <Clock size={15} />
          <span>{clockStr}</span>
        </div>

        <div className={`backend-badge ${backendStatus ? 'connected' : 'standalone'}`}>
          {backendStatus ? (
            <>
              <CheckCircle2 size={14} color="#10b981" />
              <span>FastAPI Connected</span>
            </>
          ) : (
            <>
              <AlertCircle size={14} color="#f59e0b" />
              <span>Simulated Engine</span>
            </>
          )}
        </div>

        <button className="header-cta-btn" onClick={onNewRunClick}>
          <Plus size={16} />
          <span>New Test Run</span>
        </button>

        <div className="user-profile-badge">
          <div className="avatar-circle">PM</div>
          <div className="avatar-meta">
            <span className="avatar-name">Prashansha M.</span>
            <span className="avatar-role">QA Lead</span>
          </div>
        </div>
      </div>
    </header>
  );
}
