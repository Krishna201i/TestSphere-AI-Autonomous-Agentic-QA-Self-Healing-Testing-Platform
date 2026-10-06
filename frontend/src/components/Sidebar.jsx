import React from 'react';

export default function Sidebar({ activeNav, setActiveNav }) {
  const navItems = [
    { id: 'dashboard', label: 'Dashboard' },
    { id: 'projects', label: 'Projects' },
    { id: 'applications', label: 'Applications' },
    { id: 'test-cases', label: 'Test Cases' },
    { id: 'executions', label: 'Executions' },
    { id: 'failures', label: 'Failures & Healing' },
    { id: 'reports', label: 'Reports' },
    { id: 'system', label: 'System Status' },
  ];

  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-icon-wrapper">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="7"></circle>
            <ellipse cx="12" cy="12" rx="11" ry="4" transform="rotate(-30 12 12)"></ellipse>
          </svg>
        </div>
        <div className="brand-text">
          <h1>TestSphere<span>-AI</span></h1>
          <p>Autonomous Agentic QA Platform</p>
        </div>
      </div>

      <nav className="nav-menu">
        {navItems.map((item) => (
          <li 
            key={item.id} 
            className={`nav-item ${activeNav === item.id ? 'active' : ''}`}
            onClick={() => setActiveNav(item.id)}
          >
            <a href={`#${item.id}`} onClick={(e) => e.preventDefault()}>
              <span>{item.label}</span>
            </a>
          </li>
        ))}
      </nav>

      {/* Bottom AI Mascot Card */}
      <div className="sidebar-ai-widget">
        <div className="mascot-avatar">
          <img src="/assets/ai_robot_mascot.jpg" alt="AI Agent Mascot" id="mascot-img" />
        </div>
        <div className="widget-title">AI-Powered Self-Healing Testing</div>
        <div className="widget-subtitle">Plan • Execute • Diagnose<br />Heal • Validate • Persist</div>
      </div>
    </aside>
  );
}
