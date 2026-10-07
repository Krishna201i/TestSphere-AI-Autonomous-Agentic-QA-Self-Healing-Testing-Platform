import React, { useState, useEffect } from 'react';
import { Menu, X } from 'lucide-react';

export default function Header({ 
  searchQuery, 
  setSearchQuery, 
  backendStatus,
  onToggleMobileMenu,
  isMobileMenuOpen 
}) {
  const [clockStr, setClockStr] = useState('');

  useEffect(() => {
    function updateTime() {
      const now = new Date();
      const options = { weekday: 'short', month: 'short', day: 'numeric' };
      const datePart = now.toLocaleDateString('en-US', options);
      const timePart = now.toLocaleTimeString('en-US', { hour12: true });
      setClockStr(`${datePart} | ${timePart}`);
    }
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header className="top-header">
      <div className="header-left-group">
        {/* Mobile Hamburger Menu Toggle Button */}
        <button 
          type="button"
          className="mobile-menu-toggle"
          onClick={onToggleMobileMenu}
          aria-label={isMobileMenuOpen ? "Close navigation menu" : "Open navigation menu"}
        >
          {isMobileMenuOpen ? <X size={20} /> : <Menu size={20} />}
        </button>

        <div className="search-wrapper">
          <svg className="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8"></circle>
            <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
          </svg>
          <input 
            type="text" 
            className="search-input" 
            id="global-search" 
            placeholder="Search projects, test cases, executions..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          <span className="search-keycap">Ctrl K</span>
        </div>
      </div>

      <div className="header-right">
        {/* System Status Pill */}
        <div className="status-badge-healthy">
          <span className="status-dot-pulse"></span>
          <span>{backendStatus ? 'FastAPI Connected' : 'Simulated Engine'}</span>
        </div>

        {/* User Profile */}
        <div className="user-profile">
          <div className="user-avatar">PM</div>
          <div className="user-meta">
            <span className="user-name">Prashansha</span>
            <span className="user-role">QA Lead</span>
          </div>
        </div>

        {/* Date & Time Digital Clock */}
        <div className="clock-display">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
            <line x1="16" y1="2" x2="16" y2="6"></line>
            <line x1="8" y1="2" x2="8" y2="6"></line>
            <line x1="3" y1="10" x2="21" y2="10"></line>
          </svg>
          <span id="live-clock">{clockStr}</span>
        </div>
      </div>
    </header>
  );
}
