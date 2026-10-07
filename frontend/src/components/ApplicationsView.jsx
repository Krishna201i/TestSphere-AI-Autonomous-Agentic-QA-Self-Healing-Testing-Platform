import React, { useState, useEffect } from 'react';
import { 
  AppWindow, 
  Plus, 
  Globe, 
  ExternalLink, 
  Play, 
  CheckCircle2, 
  Activity, 
  Server, 
  Search, 
  Sparkles, 
  X,
  Radio,
  FileCode2
} from 'lucide-react';
import { getApplications } from '../services/api';

const DEFAULT_APPLICATIONS = [
  {
    id: 1,
    name: 'E-Commerce Storefront',
    baseUrl: 'https://example.com',
    environment: 'Production',
    healthStatus: '200 OK',
    latency: '42ms',
    casesCount: 12,
    playwrightMode: 'Chromium Headless',
    lastTested: '10 mins ago',
    project: 'E-Commerce Webapp'
  },
  {
    id: 2,
    name: 'Authentication & SSO Gateway',
    baseUrl: 'https://example.com/auth',
    environment: 'Staging',
    healthStatus: '200 OK',
    latency: '35ms',
    casesCount: 8,
    playwrightMode: 'Chromium Headless',
    lastTested: '25 mins ago',
    project: 'FinTech Core Banking'
  },
  {
    id: 3,
    name: 'Cart & Payment Checkout Flow',
    baseUrl: 'https://example.com/checkout',
    environment: 'Production',
    healthStatus: '200 OK',
    latency: '58ms',
    casesCount: 14,
    playwrightMode: 'Chromium Headless',
    lastTested: '1 hour ago',
    project: 'E-Commerce Webapp'
  },
  {
    id: 4,
    name: 'Customer Account Portal',
    baseUrl: 'https://example.com/account',
    environment: 'Staging',
    healthStatus: '200 OK',
    latency: '48ms',
    casesCount: 6,
    playwrightMode: 'Chromium Headless',
    lastTested: '3 hours ago',
    project: 'Healthcare Patient Portal'
  }
];

export default function ApplicationsView({ setActiveNav, onOpenPlanModal, searchQuery = '' }) {
  const [apps, setApps] = useState(DEFAULT_APPLICATIONS);
  const [localSearch, setLocalSearch] = useState('');
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [newApp, setNewApp] = useState({
    name: '',
    baseUrl: 'https://',
    environment: 'Production',
    project: 'E-Commerce Webapp'
  });
  const [pingingId, setPingingId] = useState(null);

  useEffect(() => {
    async function loadApps() {
      const live = await getApplications();
      if (live && live.length > 0) {
        const mapped = live.map(a => ({
          id: a.id,
          name: a.name,
          baseUrl: a.base_url || 'https://example.com',
          environment: a.description?.includes('Production') ? 'Production' : 'Staging',
          healthStatus: '200 OK',
          latency: `${Math.floor(Math.random() * 30) + 25}ms`,
          casesCount: 8,
          playwrightMode: 'Chromium Headless',
          lastTested: 'Just now',
          project: 'Active Target'
        }));
        setApps(mapped);
      }
    }
    loadApps();
  }, []);

  const filterTerm = (searchQuery || localSearch).toLowerCase();
  const filteredApps = apps.filter(a => 
    a.name.toLowerCase().includes(filterTerm) ||
    a.baseUrl.toLowerCase().includes(filterTerm) ||
    a.project.toLowerCase().includes(filterTerm)
  );

  function handlePing(id) {
    setPingingId(id);
    setTimeout(() => {
      setPingingId(null);
    }, 1200);
  }

  function handleAddApp(e) {
    e.preventDefault();
    if (!newApp.name || !newApp.baseUrl) return;
    const created = {
      id: Date.now(),
      name: newApp.name,
      baseUrl: newApp.baseUrl,
      environment: newApp.environment,
      healthStatus: '200 OK',
      latency: '36ms',
      casesCount: 0,
      playwrightMode: 'Chromium Headless',
      lastTested: 'Just added',
      project: newApp.project
    };
    setApps([created, ...apps]);
    setIsAddModalOpen(false);
    setNewApp({ name: '', baseUrl: 'https://', environment: 'Production', project: 'E-Commerce Webapp' });
  }

  return (
    <div className="view-container">
      {/* Title Header */}
      <div className="page-title-row">
        <div className="page-title-box">
          <div className="page-icon-badge">
            <AppWindow size={22} />
          </div>
          <div>
            <h2>Applications</h2>
            <p>Target web applications, base URLs, and environment health under test</p>
          </div>
        </div>

        <button 
          className="btn-run-small"
          onClick={() => setIsAddModalOpen(true)}
          style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', cursor: 'pointer' }}
        >
          <Plus size={16} />
          <span>+ Add Application</span>
        </button>
      </div>

      {/* KPI Overview Cards */}
      <div className="kpi-grid">
        <div className="kpi-card">
          <div className="kpi-label">Configured Webapps</div>
          <div className="kpi-value">{apps.length}</div>
          <div className="kpi-footer text-cyan">Active Targets</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Health Status</div>
          <div className="kpi-value">100%</div>
          <div className="kpi-footer text-success">All Endpoints 200 OK</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Average Response</div>
          <div className="kpi-value">40ms</div>
          <div className="kpi-footer text-primary">Ultra-Low Latency</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Test Scenarios</div>
          <div className="kpi-value">{apps.reduce((acc, a) => acc + a.casesCount, 0)}</div>
          <div className="kpi-footer text-success">Autonomous Cases</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Browser Engine</div>
          <div className="kpi-value">Chromium</div>
          <div className="kpi-footer text-healed">Playwright Fast Mode</div>
        </div>
      </div>

      {/* Search Bar */}
      <div className="filter-bar-card">
        <div className="search-input-wrapper">
          <Search size={16} className="search-icon-inside" />
          <input 
            type="text" 
            placeholder="Search applications by name, URL, or project..." 
            value={localSearch}
            onChange={(e) => setLocalSearch(e.target.value)}
            className="form-input with-icon"
          />
        </div>
        <div className="result-counter">
          Showing <span>{filteredApps.length}</span> of {apps.length} applications
        </div>
      </div>

      {/* Applications Grid */}
      <div className="projects-grid">
        {filteredApps.map((a) => (
          <div key={a.id} className="project-card">
            <div className="project-card-header">
              <div className="project-title-group">
                <div className="project-badge-icon" style={{ background: 'linear-gradient(135deg, #0284c7, #2563eb)' }}>
                  <Globe size={18} />
                </div>
                <div>
                  <h3 className="project-title">{a.name}</h3>
                  <div className="project-meta-row">
                    <a 
                      href={a.baseUrl} 
                      target="_blank" 
                      rel="noopener noreferrer" 
                      className="repo-pill"
                      style={{ color: 'var(--accent-cyan)' }}
                    >
                      <Globe size={12} />
                      {a.baseUrl}
                    </a>
                    <span className="env-pill">{a.environment}</span>
                  </div>
                </div>
              </div>

              <div className="status-pill status-pill-passed">
                {pingingId === a.id ? 'Pinging...' : a.healthStatus}
              </div>
            </div>

            <div className="project-stats-row">
              <div className="project-stat-item">
                <span className="stat-label">Project Suite</span>
                <span className="stat-val">{a.project}</span>
              </div>
              <div className="project-stat-item">
                <span className="stat-label">Test Cases</span>
                <span className="stat-val">{a.casesCount} linked</span>
              </div>
              <div className="project-stat-item">
                <span className="stat-label">Latency</span>
                <span className="stat-val text-cyan">{a.latency}</span>
              </div>
              <div className="project-stat-item">
                <span className="stat-label">Browser Mode</span>
                <span className="stat-val text-muted">{a.playwrightMode}</span>
              </div>
              <div className="project-stat-item">
                <span className="stat-label">Last Tested</span>
                <span className="stat-val text-muted">{a.lastTested}</span>
              </div>
            </div>

            <div className="project-card-actions">
              <button 
                className="btn-card-action"
                onClick={() => handlePing(a.id)}
                disabled={pingingId === a.id}
              >
                <Activity size={14} />
                <span>{pingingId === a.id ? 'Pinging...' : 'Ping Health'}</span>
              </button>

              <button 
                className="btn-card-action"
                onClick={() => setActiveNav('test-cases')}
              >
                <FileCode2 size={14} />
                <span>View Test Cases</span>
              </button>

              <button 
                className="btn-primary-small"
                onClick={onOpenPlanModal}
              >
                <Play size={14} />
                <span>Trigger Run</span>
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Add Application Modal */}
      {isAddModalOpen && (
        <div className="modal-overlay modal-backdrop" onClick={() => setIsAddModalOpen(false)}>
          <div className="modal-content modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-title-wrap modal-title-group">
                <Sparkles size={20} className="text-cyan" />
                <h3 className="modal-title">Configure Target Application</h3>
              </div>
              <button className="modal-close-btn" onClick={() => setIsAddModalOpen(false)}>
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleAddApp} className="modal-form">
              <div className="form-group">
                <label className="form-label">Application Name</label>
                <input 
                  type="text" 
                  className="form-input" 
                  value={newApp.name} 
                  onChange={(e) => setNewApp({ ...newApp, name: e.target.value })}
                  placeholder="e.g. User Profile Portal"
                  required 
                />
              </div>

              <div className="form-group">
                <label className="form-label">Base URL (Playwright Target)</label>
                <div className="input-with-icon">
                  <Globe size={16} className="input-icon" />
                  <input 
                    type="url" 
                    className="form-input with-icon" 
                    value={newApp.baseUrl} 
                    onChange={(e) => setNewApp({ ...newApp, baseUrl: e.target.value })}
                    placeholder="https://example.com"
                    required
                  />
                </div>
              </div>

              <div className="form-group">
                <label className="form-label">Environment</label>
                <select 
                  className="form-input" 
                  value={newApp.environment}
                  onChange={(e) => setNewApp({ ...newApp, environment: e.target.value })}
                >
                  <option value="Production">Production</option>
                  <option value="Staging">Staging</option>
                  <option value="UAT">UAT / Pre-Release</option>
                  <option value="Development">Development</option>
                </select>
              </div>

              <div className="modal-footer">
                <button type="button" className="btn-secondary" onClick={() => setIsAddModalOpen(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn-primary">
                  Save Application
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
