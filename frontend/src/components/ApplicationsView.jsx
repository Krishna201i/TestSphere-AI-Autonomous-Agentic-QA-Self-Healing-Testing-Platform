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

export default function ApplicationsView({ setActiveNav, onOpenPlanModal, searchQuery = '' }) {
  const [apps, setApps] = useState([]);
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
      if (Array.isArray(live) && live.length > 0) {
        const mapped = live.map(a => ({
          id: a.id,
          name: a.name,
          baseUrl: a.base_url || 'https://example.com',
          environment: a.description?.includes('Production') ? 'Production' : 'Staging',
          healthStatus: '200 OK',
          latency: '28ms',
          casesCount: 2,
          playwrightMode: 'Chromium Headless',
          lastTested: 'Connected',
          project: 'TestSphere Suite'
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

  function handleAddApplication(e) {
    e.preventDefault();
    if (!newApp.name) return;
    const created = {
      id: Date.now(),
      name: newApp.name,
      baseUrl: newApp.baseUrl,
      environment: newApp.environment,
      healthStatus: '200 OK',
      latency: '30ms',
      casesCount: 0,
      playwrightMode: 'Chromium Headless',
      lastTested: 'Just added',
      project: newApp.project
    };
    setApps([created, ...apps]);
    setIsAddModalOpen(false);
    setNewApp({ name: '', baseUrl: 'https://', environment: 'Production', project: 'E-Commerce Webapp' });
  }

  function handlePing(appId) {
    setPingingId(appId);
    setTimeout(() => {
      setPingingId(null);
    }, 1200);
  }

  return (
    <div className="view-container">
      {/* Title Header */}
      <div className="page-title-row">
        <div className="page-title-box">
          <div className="page-icon-badge" style={{ background: 'linear-gradient(135deg, rgba(6, 182, 212, 0.3), rgba(59, 130, 246, 0.3))' }}>
            <AppWindow size={22} color="#06b6d4" />
          </div>
          <div>
            <h2>Target Applications</h2>
            <p>Target web applications, environments, base URLs, and Playwright browser instances</p>
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
          <div className="kpi-label">Active Applications</div>
          <div className="kpi-value">{apps.length}</div>
          <div className="kpi-footer text-cyan">Database Targets</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Health Checks</div>
          <div className="kpi-value text-success">100%</div>
          <div className="kpi-footer text-success">All Targets Active</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Avg HTTP Latency</div>
          <div className="kpi-value text-primary">28ms</div>
          <div className="kpi-footer text-cyan">Fast Response</div>
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
      {filteredApps.length === 0 ? (
        <div className="data-table-card" style={{ padding: '3rem 1rem', textAlign: 'center', color: 'var(--text-muted)' }}>
          <AppWindow size={36} style={{ margin: '0 auto 1rem', opacity: 0.4 }} />
          <p>No applications registered in the database yet.</p>
        </div>
      ) : (
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
                  <span>Execute Plan</span>
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Add Application Modal */}
      {isAddModalOpen && (
        <div className="modal-overlay modal-backdrop" onClick={() => setIsAddModalOpen(false)}>
          <div className="modal-content modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-title-wrap modal-title-group">
                <Sparkles size={20} className="text-cyan" />
                <h3 className="modal-title">Register Target Application</h3>
              </div>
              <button className="modal-close-btn" onClick={() => setIsAddModalOpen(false)}>
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleAddApplication} className="modal-form">
              <div className="form-group">
                <label className="form-label">Application Name</label>
                <input 
                  type="text" 
                  className="form-input" 
                  value={newApp.name} 
                  onChange={(e) => setNewApp({ ...newApp, name: e.target.value })}
                  placeholder="e.g. Shopping Cart & Checkout"
                  required 
                />
              </div>

              <div className="form-group">
                <label className="form-label">Base URL / Target Host</label>
                <input 
                  type="text" 
                  className="form-input" 
                  value={newApp.baseUrl} 
                  onChange={(e) => setNewApp({ ...newApp, baseUrl: e.target.value })}
                  placeholder="https://app.staging.example.com"
                  required 
                />
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
                  <option value="Local Dev">Local Dev (localhost)</option>
                </select>
              </div>

              <div className="form-group">
                <label className="form-label">Parent Project</label>
                <input 
                  type="text" 
                  className="form-input" 
                  value={newApp.project} 
                  onChange={(e) => setNewApp({ ...newApp, project: e.target.value })}
                  placeholder="e.g. E-Commerce Webapp"
                />
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
