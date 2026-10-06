import React from 'react';
import { 
  LayoutDashboard, 
  FlaskConical, 
  PlayCircle, 
  AlertTriangle, 
  Wand2, 
  BarChart3, 
  Settings, 
  Bot,
  Activity,
  Layers
} from 'lucide-react';

export default function Sidebar({ activeNav, setActiveNav, backendStatus, onNewRunClick }) {
  const navItems = [
    { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { id: 'test-cases', label: 'Test Cases', icon: FlaskConical },
    { id: 'executions', label: 'Executions', icon: PlayCircle },
    { id: 'diagnostics', label: 'Failure Analyzer', icon: AlertTriangle },
    { id: 'healing', label: 'Self-Healing Hub', icon: Wand2 },
    { id: 'analytics', label: 'Analytics & KPIs', icon: BarChart3 },
    { id: 'settings', label: 'Settings', icon: Settings },
  ];

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="brand-logo-container">
          <img 
            src="/assets/ai_robot_mascot.jpg" 
            alt="AI Robot" 
            className="brand-mascot-img"
            onError={(e) => {
              // fallback if missing
              e.target.style.display = 'none';
            }} 
          />
          <div className="brand-icon-fallback">
            <Bot size={22} color="#818cf8" />
          </div>
        </div>
        <div className="brand-titles">
          <span className="brand-name">TestSphere-AI</span>
          <span className="brand-subtitle">Autonomous QA Agent</span>
        </div>
      </div>

      <div className="sidebar-context">
        <label className="context-label">ACTIVE WORKSPACE</label>
        <div className="context-card">
          <Layers size={16} className="context-icon" />
          <div className="context-info">
            <span className="context-project">E-Commerce Webapp</span>
            <span className="context-app">Staging v2.4.1</span>
          </div>
        </div>
      </div>

      <nav className="sidebar-nav">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeNav === item.id;
          return (
            <button
              key={item.id}
              className={`nav-item ${isActive ? 'active' : ''}`}
              onClick={() => setActiveNav(item.id)}
            >
              <Icon size={18} className="nav-icon" />
              <span>{item.label}</span>
              {item.id === 'healing' && <span className="nav-pill">AI Auto</span>}
            </button>
          );
        })}
      </nav>

      <div className="sidebar-footer">
        <button className="primary-action-btn" onClick={onNewRunClick}>
          <PlayCircle size={18} />
          <span>Plan & Execute</span>
        </button>

        <div className="engine-status-pill">
          <span className={`status-dot ${backendStatus ? 'online' : 'offline'}`} />
          <div className="status-meta">
            <span className="status-label">Engine & Agents</span>
            <span className="status-sub">{backendStatus ? 'Connected (Playwright/FastAPI)' : 'Standalone Preview'}</span>
          </div>
        </div>
      </div>
    </aside>
  );
}
