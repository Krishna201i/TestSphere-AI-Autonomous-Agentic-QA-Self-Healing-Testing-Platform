import React, { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import Header from './components/Header';
import MetricsOverview from './components/MetricsOverview';
import LiveExecutionConsole from './components/LiveExecutionConsole';
import TestCaseTable from './components/TestCaseTable';
import PlanExecuteModal from './components/PlanExecuteModal';
import ProjectsView from './components/ProjectsView';
import ApplicationsView from './components/ApplicationsView';
import TestCasesView from './components/TestCasesView';
import ExecutionsView from './components/ExecutionsView';
import FailuresHealingView from './components/FailuresHealingView';
import ReportsView from './components/ReportsView';
import SystemStatusView from './components/SystemStatusView';
import { 
  checkBackendHealth, 
  getTestCases, 
  getTestExecutions,
  planAndExecuteWorkflow,
  subscribeToWorkflowStream 
} from './services/api';

const DEFAULT_TEST_CASES = [
  {
    id: 'TC_LOGIN_001',
    name: 'User Login & Auth',
    category: 'Authentication',
    priority: 'High',
    version: '1.2',
    outcome: 'HEALED',
    duration: '2m 34s',
    logs: [
      { time: '10:24:03', text: 'Starting test execution for test case: TC_LOGIN_001', type: 'info' },
      { time: '10:24:05', text: 'Navigating to https://example.com/login', type: 'default' },
      { time: '10:24:12', text: 'Waiting for DOM elements to load...', type: 'default' },
      { time: '10:24:18', text: 'Entering credentials for testuser', type: 'default' },
      { time: '10:24:25', text: 'Clicking submit button with locator `#login-btn`', type: 'default' },
      { time: '10:24:28', text: 'Locator timeout: #login-btn not found. Triggering Failure Analyzer Agent...', type: 'warn' },
      { time: '10:24:30', text: 'FailureAnalyzer diagnosed LOCATOR_CHANGED (Confidence: 92%)', type: 'agent' },
      { time: '10:24:32', text: 'Candidate selector generated: button[type="submit"]', type: 'agent' },
      { time: '10:24:35', text: 'Playwright engine validating replacement selector in isolated context...', type: 'default' },
      { time: '10:24:38', text: 'Validation SUCCESS! Test step healed and state persisted to DB.', type: 'success' },
    ],
    failure: {
      category: 'Element Not Found',
      rootCause: 'Login button selector changed from `#login-btn`',
      details: "Element with selector '#login-btn' not found in current DOM snapshot. The button was modified during staging deploy.",
      evidenceImg: '/assets/evidence_preview.jpg',
    },
    healing: {
      candidate: 'CSS Selector Update',
      confidence: '92%',
      oldSelector: '#login-btn',
      newSelector: 'button[type="submit"]',
      validation: 'Successfully Validated by Engine',
      status: 'Healing Successful',
    },
  },
  {
    id: 'TC_CART_002',
    name: 'Add Item to Cart',
    category: 'E-Commerce',
    priority: 'High',
    version: '1.0',
    outcome: 'FAILED',
    duration: '1m 12s',
    logs: [
      { time: '10:12:00', text: 'Starting execution for test case: TC_CART_002', type: 'info' },
      { time: '10:12:04', text: 'Navigating to https://example.com/products/item-42', type: 'default' },
      { time: '10:12:08', text: 'Clicking button[data-testid="add-to-cart"]', type: 'default' },
      { time: '10:12:12', text: 'Server returned HTTP 500 Internal Server Error', type: 'error' },
      { time: '10:12:14', text: 'Failure categorized as APPLICATION_BUG. Non-healable regression.', type: 'error' },
    ],
    failure: {
      category: 'API 500 Error',
      rootCause: 'Backend cart service exception during checkout',
      details: 'HTTP 500 Internal Server Error received from /api/cart/add endpoint.',
      evidenceImg: '/assets/evidence_preview.jpg',
    },
    healing: {
      candidate: 'None (Application Bug)',
      confidence: '0%',
      oldSelector: 'N/A',
      newSelector: 'N/A',
      validation: 'Self-healing aborted — true application bug',
      status: 'Heal Skipped (Bug)',
    },
  },
  {
    id: 'TC_CHECKOUT_003',
    name: 'Complete Checkout Flow',
    category: 'E-Commerce',
    priority: 'Medium',
    version: '1.0',
    outcome: 'PASSED',
    duration: '3m 18s',
    logs: [
      { time: '09:58:10', text: 'Starting execution for test case: TC_CHECKOUT_003', type: 'info' },
      { time: '09:58:15', text: 'Navigating to https://example.com/checkout', type: 'default' },
      { time: '09:58:25', text: 'Filling shipping and payment form details...', type: 'default' },
      { time: '09:58:35', text: 'Submitting payment order #ord-9821', type: 'default' },
      { time: '09:58:43', text: 'Order confirmation received. All assertions passed.', type: 'success' },
    ],
    failure: {
      category: 'None',
      rootCause: 'All steps executed deterministically',
      details: 'No locator drift or application assertion errors detected.',
      evidenceImg: '/assets/evidence_preview.jpg',
    },
    healing: {
      candidate: 'Not Needed',
      confidence: '100%',
      oldSelector: 'N/A',
      newSelector: 'N/A',
      validation: 'Original locators validated successfully',
      status: 'Test Passed Cleanly',
    },
  },
  {
    id: 'TC_SEARCH_004',
    name: 'Search Product Catalog',
    category: 'Search & Filter',
    priority: 'Medium',
    version: '1.0',
    outcome: 'PASSED',
    duration: '1m 45s',
    logs: [
      { time: '09:34:21', text: 'Starting execution for test case: TC_SEARCH_004', type: 'info' },
      { time: '09:34:25', text: 'Querying catalog with "wireless headphones"', type: 'default' },
      { time: '09:34:30', text: '12 products returned in catalog grid.', type: 'success' },
    ],
    failure: {
      category: 'None',
      rootCause: 'Search returned expected result list',
      details: 'No regression found.',
      evidenceImg: '/assets/evidence_preview.jpg',
    },
    healing: {
      candidate: 'Not Needed',
      confidence: '100%',
      oldSelector: 'N/A',
      newSelector: 'N/A',
      validation: 'Original locators validated successfully',
      status: 'Test Passed Cleanly',
    },
  },
  {
    id: 'TC_PROFILE_005',
    name: 'Update User Profile Info',
    category: 'User Account',
    priority: 'Low',
    version: '1.0',
    outcome: 'FAILED',
    duration: '2m 11s',
    logs: [
      { time: '09:12:07', text: 'Starting execution for test case: TC_PROFILE_005', type: 'info' },
      { time: '09:12:15', text: 'Navigating to /account/profile', type: 'default' },
      { time: '09:12:20', text: 'Timeout waiting for avatar upload button', type: 'error' },
    ],
    failure: {
      category: 'Timeout Error',
      rootCause: 'Profile form unresponsive',
      details: 'Avatar button failed to respond to click event within 3000ms.',
      evidenceImg: '/assets/evidence_preview.jpg',
    },
    healing: {
      candidate: 'Increase Timeout or Retry',
      confidence: '45%',
      oldSelector: 'button#avatar-upload',
      newSelector: 'input[type="file"]',
      validation: 'Validation pending',
      status: 'Pending Verification',
    },
  },
];

export default function App() {
  const [activeNav, setActiveNav] = useState('dashboard');
  const [backendStatus, setBackendStatus] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [testCases, setTestCases] = useState(DEFAULT_TEST_CASES);
  const [activeTestCaseId, setActiveTestCaseId] = useState('TC_LOGIN_001');
  const [currentStepIndex, setCurrentStepIndex] = useState(1); // 1 = EXECUTE
  const [timerSeconds, setTimerSeconds] = useState(78);
  const [isRunning, setIsRunning] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [executions, setExecutions] = useState([]);

  const activeTestCase = testCases.find(t => t.id === activeTestCaseId) || testCases[0];

  // Check backend health & fetch live data on load
  useEffect(() => {
    async function initPlatform() {
      const health = await checkBackendHealth();
      if (health && (health.status === 'healthy' || health.status === 'ok')) {
        setBackendStatus(true);
        const [liveCases, liveExecutions] = await Promise.all([
          getTestCases(),
          getTestExecutions(),
        ]);
        if (liveExecutions && liveExecutions.length > 0) {
          setExecutions(liveExecutions);
        }
        if (liveCases && liveCases.length > 0) {
          const merged = liveCases.map((lc, idx) => {
            const relatedExecs = (liveExecutions || []).filter(e => e.test_case_id === lc.id);
            const latestExec = relatedExecs[relatedExecs.length - 1];
            const outcome = latestExec ? latestExec.status : 'PENDING';
            const duration = latestExec?.duration_ms ? `${(latestExec.duration_ms / 1000).toFixed(1)}s` : '—';

            return {
              id: lc.external_id || `TC-${lc.id}`,
              db_id: lc.id,
              name: lc.name,
              category: lc.category || 'Functional',
              priority: lc.priority || 'High',
              version: `${lc.version || 1}.0`,
              outcome: outcome,
              duration: duration,
              error_message: latestExec?.error_message,
              logs: latestExec ? [
                { time: new Date(latestExec.started_at || Date.now()).toLocaleTimeString(), text: `Execution Run #${latestExec.id} initiated`, type: 'info' },
                { time: new Date(latestExec.completed_at || Date.now()).toLocaleTimeString(), text: latestExec.error_message ? `Failed: ${latestExec.error_message}` : `Execution completed: ${latestExec.status}`, type: latestExec.error_message ? 'error' : 'success' },
              ] : (DEFAULT_TEST_CASES[idx % DEFAULT_TEST_CASES.length]?.logs || DEFAULT_TEST_CASES[0].logs),
              failure: latestExec?.error_message ? {
                step: 'Target Action',
                errorType: 'EXECUTION_FAILURE',
                message: latestExec.error_message,
                timestamp: latestExec.completed_at || new Date().toISOString(),
              } : (DEFAULT_TEST_CASES[idx % DEFAULT_TEST_CASES.length]?.failure || DEFAULT_TEST_CASES[0].failure),
              healing: DEFAULT_TEST_CASES[idx % DEFAULT_TEST_CASES.length]?.healing || DEFAULT_TEST_CASES[0].healing,
            };
          });
          setTestCases(merged);
          if (merged.length > 0) {
            setActiveTestCaseId(merged[0].id);
          }
        }
      }
    }
    initPlatform();
  }, []);

  // Timer interval
  useEffect(() => {
    if (!isRunning) return;
    const interval = setInterval(() => {
      setTimerSeconds(s => s + 1);
    }, 1000);
    return () => clearInterval(interval);
  }, [isRunning]);

  // Handle new execution start
  function handleExecutionStarted(result) {
    const newId = `TC_RUN_${Date.now().toString().slice(-4)}`;
    const newCase = {
      id: newId,
      db_id: result.test_case_id,
      name: result.test_case_name || 'Autonomous Flow Execution',
      category: 'Autonomous',
      priority: 'High',
      version: '1.0',
      outcome: result.status || 'PASSED',
      duration: `${result.duration_ms ? (result.duration_ms / 1000).toFixed(1) + 's' : '2.4s'}`,
      logs: (result.events || []).map(e => ({
        time: new Date().toLocaleTimeString('en-US', { hour12: false }),
        text: `[${e.event_type}] ${e.message}`,
        type: e.event_type.includes('COMPLETED') || e.event_type.includes('SUCCESS') ? 'success' : (e.event_type.includes('FAILURE') ? 'error' : 'agent'),
      })),
      failure: DEFAULT_TEST_CASES[0].failure,
      healing: DEFAULT_TEST_CASES[0].healing,
    };

    setTestCases([newCase, ...testCases]);
    setActiveTestCaseId(newId);
    setTimerSeconds(0);
    setCurrentStepIndex(result.status === 'HEALED' ? 4 : (result.status === 'PASSED' ? 5 : 2));

    getTestExecutions().then(execs => {
      if (execs && execs.length > 0) setExecutions(execs);
    });

    if (result.execution_id) {
      subscribeToWorkflowStream(
        result.execution_id,
        (event) => {
          console.log('Live SSE Event:', event);
        },
        () => {
          console.log('Stream ended.');
        }
      );
    }
  }

  function handleSelectTestCase(id) {
    setActiveTestCaseId(id);
    const tc = testCases.find(t => t.id === id);
    if (!tc) return;

    if (tc.outcome === 'HEALED') setCurrentStepIndex(3);
    else if (tc.outcome === 'PASSED') setCurrentStepIndex(5);
    else setCurrentStepIndex(2);
  }

  async function handleRunTest(tc) {
    handleSelectTestCase(tc.id);
    setTimerSeconds(0);
    setIsRunning(true);
    setCurrentStepIndex(0); // PLAN

    const stepTimer = setTimeout(() => setCurrentStepIndex(1), 500); // EXECUTE

    try {
      const tcId = tc.db_id || (typeof tc.id === 'number' ? tc.id : null);
      const res = await planAndExecuteWorkflow({
        test_case_id: tcId,
        test_case_name: tc.name,
        headless: true,
      });

      const finalStatus = res.status || 'PASSED';
      const durationSec = res.duration_ms ? `${(res.duration_ms / 1000).toFixed(1)}s` : '1.5s';
      const events = res.events || [];

      const liveLogs = events.map(e => ({
        time: new Date().toLocaleTimeString('en-US', { hour12: false }),
        text: `[${e.event_type}] ${e.message}`,
        type: e.event_type.includes('COMPLETED') || e.event_type.includes('SUCCESS') ? 'success' : (e.event_type.includes('FAILURE') ? 'error' : 'agent'),
      }));

      if (finalStatus === 'HEALED') setCurrentStepIndex(4);
      else if (finalStatus === 'PASSED') setCurrentStepIndex(5);
      else setCurrentStepIndex(2);

      setTestCases(prev => prev.map(item => item.id === tc.id ? {
        ...item,
        outcome: finalStatus,
        duration: durationSec,
        logs: liveLogs.length > 0 ? liveLogs : item.logs,
      } : item));

      const refreshed = await getTestExecutions();
      if (refreshed && refreshed.length > 0) {
        setExecutions(refreshed);
      }
    } catch (err) {
      console.warn('Real test run caught error:', err.message);
      setTimeout(() => {
        if (tc.outcome === 'HEALED') setCurrentStepIndex(4);
        else if (tc.outcome === 'PASSED') setCurrentStepIndex(5);
        else setCurrentStepIndex(2);
      }, 1000);
    } finally {
      clearTimeout(stepTimer);
      setIsRunning(false);
    }
  }

  return (
    <div className="app-container">
      <Sidebar 
        activeNav={activeNav} 
        setActiveNav={setActiveNav}
        isOpen={isMobileMenuOpen}
        onClose={() => setIsMobileMenuOpen(false)}
      />

      <main className="main-content">
        <Header 
          searchQuery={searchQuery}
          setSearchQuery={setSearchQuery}
          backendStatus={backendStatus}
          onToggleMobileMenu={() => setIsMobileMenuOpen(prev => !prev)}
          isMobileMenuOpen={isMobileMenuOpen}
        />

        {activeNav === 'dashboard' && (
          <div className="dashboard-body">
            {/* Page Header Title */}
            <div className="page-title-row">
              <div className="page-title-box">
                <div className="page-icon-badge">
                  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <circle cx="12" cy="12" r="6"></circle>
                    <circle cx="12" cy="12" r="2"></circle>
                  </svg>
                </div>
                <div>
                  <h2>Dashboard</h2>
                  <p>Monitor and manage your autonomous QA testing workflows</p>
                </div>
              </div>

              <button 
                className="btn-run-small" 
                style={{ 
                  padding: '0.65rem 1.25rem', 
                  fontSize: '0.84rem', 
                  display: 'flex', 
                  alignItems: 'center', 
                  gap: '0.45rem',
                  cursor: 'pointer' 
                }}
                onClick={() => setIsModalOpen(true)}
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <line x1="12" y1="5" x2="12" y2="19"></line>
                  <line x1="5" y1="12" x2="19" y2="12"></line>
                </svg>
                <span>+ Plan & Execute Test</span>
              </button>
            </div>

            {/* 5 KPI METRICS CARDS */}
            <MetricsOverview stats={{
              totalTests: testCases.length,
              passRate: 97.4,
              healedCount: testCases.filter(c => c.outcome === 'HEALED').length,
              avgDuration: '2m 34s',
            }} />

            {/* Live Execution & Diagnostics Grid */}
            <LiveExecutionConsole 
              activeRun={activeTestCase}
              logs={activeTestCase?.logs || []}
              timerSeconds={timerSeconds}
              isRunning={isRunning}
              onTogglePlay={() => setIsRunning(!isRunning)}
              onReset={() => handleRunTest(activeTestCase)}
              currentStepIndex={currentStepIndex}
              onStepClick={(index) => setCurrentStepIndex(index)}
            />

            {/* Bottom Data Tables */}
            <TestCaseTable 
              testCases={testCases}
              executions={executions}
              activeTestCaseId={activeTestCaseId}
              onSelectTestCase={handleSelectTestCase}
              onRunTest={handleRunTest}
            />
          </div>
        )}

        {activeNav === 'projects' && (
          <ProjectsView 
            setActiveNav={setActiveNav}
            onOpenPlanModal={() => setIsModalOpen(true)}
            searchQuery={searchQuery}
          />
        )}

        {activeNav === 'applications' && (
          <ApplicationsView 
            setActiveNav={setActiveNav}
            onOpenPlanModal={() => setIsModalOpen(true)}
            searchQuery={searchQuery}
          />
        )}

        {activeNav === 'test-cases' && (
          <TestCasesView 
            testCases={testCases}
            onRunTest={handleRunTest}
            onSelectTestCase={handleSelectTestCase}
            searchQuery={searchQuery}
            onOpenPlanModal={() => setIsModalOpen(true)}
          />
        )}

        {activeNav === 'executions' && (
          <ExecutionsView 
            executions={executions}
            onOpenPlanModal={() => setIsModalOpen(true)}
            searchQuery={searchQuery}
          />
        )}

        {activeNav === 'failures' && (
          <FailuresHealingView 
            executions={executions}
            onOpenPlanModal={() => setIsModalOpen(true)}
          />
        )}

        {activeNav === 'reports' && (
          <ReportsView 
            testCases={testCases}
            executions={executions}
          />
        )}

        {activeNav === 'system' && (
          <SystemStatusView 
            backendStatus={backendStatus}
          />
        )}
      </main>

      <PlanExecuteModal 
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onExecutionStarted={handleExecutionStarted}
      />
    </div>
  );
}
