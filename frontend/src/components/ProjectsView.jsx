import React, { useState, useEffect } from 'react';
import { 
  FolderKanban, 
  Plus, 
  GitBranch, 
  CheckCircle2, 
  Play, 
  ExternalLink, 
  Clock, 
  ShieldCheck, 
  Layers, 
  Search,
  X,
  Sparkles
} from 'lucide-react';
import { getProjects } from '../services/api';

const DEFAULT_PROJECTS = [
  {
    id: 1,
    name: 'E-Commerce Webapp',
    description: 'Customer-facing online storefront, product catalog, cart, and payment checkout pipelines.',
    repo: 'github.com/company/ecommerce-storefront',
    branch: 'main',
    environment: 'Production & Staging',
    suitesCount: 6,
    testCasesCount: 34,
    passRate: 98,
    healedCount: 12,
    lastRun: '12 mins ago',
    status: 'HEALTHY'
  },
  {
    id: 2,
    name: 'FinTech Core Banking Portal',
    description: 'Retail and corporate banking services, funds transfer, authentication MFA, and ledger reconciliation.',
    repo: 'github.com/company/banking-portal-core',
    branch: 'release/v2.4',
    environment: 'Staging & UAT',
    suitesCount: 5,
    testCasesCount: 52,
    passRate: 94,
    healedCount: 8,
    lastRun: '1 hour ago',
    status: 'HEALTHY'
  },
  {
    id: 3,
    name: 'Healthcare Patient Portal',
    description: 'HIPAA-compliant appointments, doctor-patient telemedicine chat, and medical records dashboard.',
    repo: 'github.com/company/health-telemed-app',
    branch: 'main',
    environment: 'Staging',
    suitesCount: 4,
    testCasesCount: 28,
    passRate: 100,
    healedCount: 4,
    lastRun: '3 hours ago',
    status: 'HEALTHY'
  },
  {
    id: 4,
    name: 'SaaS Admin & Analytics Console',
    description: 'Internal operations console, user role management, revenue telemetry, and billing portal.',
    repo: 'github.com/company/saas-ops-platform',
    branch: 'staging',
    environment: 'Production',
    suitesCount: 3,
    testCasesCount: 41,
    passRate: 88,
    healedCount: 15,
    lastRun: 'Yesterday',
    status: 'INVESTIGATING'
  }
];

export default function ProjectsView({ setActiveNav, onOpenPlanModal, searchQuery = '' }) {
  const [projects, setProjects] = useState(DEFAULT_PROJECTS);
  const [localSearch, setLocalSearch] = useState('');
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [newProject, setNewProject] = useState({
    name: '',
    description: '',
    repo: '',
    environment: 'Staging'
  });
  const [runningId, setRunningId] = useState(null);

  useEffect(() => {
    async function loadProjects() {
      const live = await getProjects();
      if (live && live.length > 0) {
        const mapped = live.map(p => ({
          id: p.id,
          name: p.name,
          description: p.description || 'Autonomous QA project suite',
          repo: 'github.com/workspace/' + (p.name.toLowerCase().replace(/\s+/g, '-')),
          branch: 'main',
          environment: 'Staging',
          suitesCount: 4,
          testCasesCount: 24,
          passRate: 96,
          healedCount: 6,
          lastRun: 'Just now',
          status: 'HEALTHY'
        }));
        setProjects([...mapped, ...DEFAULT_PROJECTS]);
      }
    }
    loadProjects();
  }, []);

  const filterTerm = (searchQuery || localSearch).toLowerCase();
  const filteredProjects = projects.filter(p => 
    p.name.toLowerCase().includes(filterTerm) ||
    p.description.toLowerCase().includes(filterTerm) ||
    p.repo.toLowerCase().includes(filterTerm)
  );

  function handleCreateProject(e) {
    e.preventDefault();
    if (!newProject.name) return;
    const created = {
      id: Date.now(),
      name: newProject.name,
      description: newProject.description || 'Autonomous test workspace for ' + newProject.name,
      repo: newProject.repo || `github.com/org/${newProject.name.toLowerCase().replace(/\s+/g, '-')}`,
      branch: 'main',
      environment: newProject.environment,
      suitesCount: 1,
      testCasesCount: 8,
      passRate: 100,
      healedCount: 0,
      lastRun: 'Just created',
      status: 'HEALTHY'
    };
    setProjects([created, ...projects]);
    setIsCreateModalOpen(false);
    setNewProject({ name: '', description: '', repo: '', environment: 'Staging' });
  }

  function handleRunProjectTests(projectId) {
    setRunningId(projectId);
    setTimeout(() => {
      setRunningId(null);
    }, 2000);
  }

  return (
    <div className="view-container">
      {/* Title Header */}
      <div className="page-title-row">
        <div className="page-title-box">
          <div className="page-icon-badge">
            <FolderKanban size={22} />
          </div>
          <div>
            <h2>Projects</h2>
            <p>Manage autonomous test suites, repositories, and workspace pipelines</p>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <button 
            className="btn-run-small"
            onClick={() => setIsCreateModalOpen(true)}
            style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', cursor: 'pointer' }}
          >
            <Plus size={16} />
            <span>+ New Project</span>
          </button>
        </div>
      </div>

      {/* KPI Overview Cards */}
      <div className="kpi-grid">
        <div className="kpi-card">
          <div className="kpi-label">Total Projects</div>
          <div className="kpi-value">{projects.length}</div>
          <div className="kpi-footer text-cyan">Active Workspaces</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Connected Repos</div>
          <div className="kpi-value">{projects.length}</div>
          <div className="kpi-footer text-success">GitHub CI/CD Synced</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Active Test Suites</div>
          <div className="kpi-value">{projects.reduce((acc, p) => acc + p.suitesCount, 0)}</div>
          <div className="kpi-footer text-primary">Automated Suites</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Avg Pass Rate</div>
          <div className="kpi-value">96.8%</div>
          <div className="kpi-footer text-success">Across All Projects</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Self-Healed Locators</div>
          <div className="kpi-value">{projects.reduce((acc, p) => acc + p.healedCount, 0)}</div>
          <div className="kpi-footer text-healed">No Manual Interventions</div>
        </div>
      </div>

      {/* Search Bar */}
      <div className="filter-bar-card">
        <div className="search-input-wrapper">
          <Search size={16} className="search-icon-inside" />
          <input 
            type="text" 
            placeholder="Filter projects by title, repository, or keyword..." 
            value={localSearch}
            onChange={(e) => setLocalSearch(e.target.value)}
            className="form-input with-icon"
          />
        </div>
        <div className="result-counter">
          Showing <span>{filteredProjects.length}</span> of {projects.length} projects
        </div>
      </div>

      {/* Projects Grid */}
      <div className="projects-grid">
        {filteredProjects.map((p) => (
          <div key={p.id} className="project-card">
            <div className="project-card-header">
              <div className="project-title-group">
                <div className="project-badge-icon">
                  <FolderKanban size={18} />
                </div>
                <div>
                  <h3 className="project-title">{p.name}</h3>
                  <div className="project-meta-row">
                    <span className="repo-pill">
                      <GitBranch size={12} />
                      {p.repo} ({p.branch})
                    </span>
                    <span className="env-pill">{p.environment}</span>
                  </div>
                </div>
              </div>

              <div className={`status-pill ${p.status === 'HEALTHY' ? 'status-pill-passed' : 'status-pill-warning'}`}>
                {p.status}
              </div>
            </div>

            <p className="project-description">{p.description}</p>

            <div className="project-stats-row">
              <div className="project-stat-item">
                <span className="stat-label">Test Cases</span>
                <span className="stat-val">{p.testCasesCount} tests</span>
              </div>
              <div className="project-stat-item">
                <span className="stat-label">Suites</span>
                <span className="stat-val">{p.suitesCount} suites</span>
              </div>
              <div className="project-stat-item">
                <span className="stat-label">Pass Rate</span>
                <span className="stat-val text-success">{p.passRate}%</span>
              </div>
              <div className="project-stat-item">
                <span className="stat-label">Auto-Healed</span>
                <span className="stat-val text-healed">{p.healedCount} healed</span>
              </div>
              <div className="project-stat-item">
                <span className="stat-label">Last Executed</span>
                <span className="stat-val text-muted">{p.lastRun}</span>
              </div>
            </div>

            <div className="project-card-actions">
              <button 
                className="btn-card-action"
                onClick={() => setActiveNav('applications')}
              >
                <Layers size={14} />
                <span>View Applications</span>
              </button>

              <button 
                className="btn-card-action"
                onClick={() => setActiveNav('test-cases')}
              >
                <ExternalLink size={14} />
                <span>View Test Cases</span>
              </button>

              <button 
                className="btn-primary-small"
                onClick={() => handleRunProjectTests(p.id)}
                disabled={runningId === p.id}
              >
                <Play size={14} />
                <span>{runningId === p.id ? 'Running Suite...' : 'Run All Tests'}</span>
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Create Project Modal */}
      {isCreateModalOpen && (
        <div className="modal-overlay modal-backdrop" onClick={() => setIsCreateModalOpen(false)}>
          <div className="modal-content modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-title-wrap modal-title-group">
                <Sparkles size={20} className="text-cyan" />
                <h3 className="modal-title">Create Testing Project</h3>
              </div>
              <button className="modal-close-btn" onClick={() => setIsCreateModalOpen(false)}>
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleCreateProject} className="modal-form">
              <div className="form-group">
                <label className="form-label">Project Name</label>
                <input 
                  type="text" 
                  className="form-input" 
                  value={newProject.name} 
                  onChange={(e) => setNewProject({ ...newProject, name: e.target.value })}
                  placeholder="e.g. Mobile Banking App"
                  required 
                />
              </div>

              <div className="form-group">
                <label className="form-label">Repository URL</label>
                <input 
                  type="text" 
                  className="form-input" 
                  value={newProject.repo} 
                  onChange={(e) => setNewProject({ ...newProject, repo: e.target.value })}
                  placeholder="github.com/company/repo"
                />
              </div>

              <div className="form-group">
                <label className="form-label">Environment</label>
                <select 
                  className="form-input" 
                  value={newProject.environment}
                  onChange={(e) => setNewProject({ ...newProject, environment: e.target.value })}
                >
                  <option value="Production">Production</option>
                  <option value="Staging">Staging</option>
                  <option value="UAT">UAT / Pre-Release</option>
                  <option value="Development">Development</option>
                </select>
              </div>

              <div className="form-group">
                <label className="form-label">Description</label>
                <textarea 
                  className="form-textarea" 
                  rows={2} 
                  value={newProject.description}
                  onChange={(e) => setNewProject({ ...newProject, description: e.target.value })}
                  placeholder="Summary of this project's testing scope..."
                />
              </div>

              <div className="modal-footer">
                <button type="button" className="btn-secondary" onClick={() => setIsCreateModalOpen(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn-primary">
                  Create Project
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
