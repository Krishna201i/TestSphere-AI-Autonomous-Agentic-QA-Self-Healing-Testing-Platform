import React from 'react';
import { 
  LayoutDashboard, 
  FolderKanban, 
  AppWindow, 
  FileCode2, 
  PlayCircle, 
  ShieldAlert, 
  BarChart3, 
  Activity 
} from 'lucide-react';

export default function Sidebar({ activeNav, setActiveNav }) {
  const navItems = [
    { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { id: 'projects', label: 'Projects', icon: FolderKanban },
    { id: 'applications', label: 'Applications', icon: AppWindow },
    { id: 'test-cases', label: 'Test Cases', icon: FileCode2 },
    { id: 'executions', label: 'Executions', icon: PlayCircle },
    { id: 'failures', label: 'Failures & Healing', icon: ShieldAlert },
    { id: 'reports', label: 'Reports', icon: BarChart3 },
    { id: 'system', label: 'System Status', icon: Activity },
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
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeNav === item.id;
          return (
            <li 
              key={item.id} 
              className={`nav-item ${isActive ? 'active' : ''}`}
            >
              <button 
                type="button"
                className="nav-link-btn"
                onClick={() => setActiveNav(item.id)}
              >
                <Icon size={18} />
                <span>{item.label}</span>
              </button>
            </li>
          );
        })}
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
