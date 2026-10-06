import React, { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import Header from './components/Header';
import MetricsOverview from './components/MetricsOverview';
import PipelineStepper from './components/PipelineStepper';
import LiveExecutionConsole from './components/LiveExecutionConsole';
import TestCaseTable from './components/TestCaseTable';
import PlanExecuteModal from './components/PlanExecuteModal';
import { 
  checkBackendHealth, 
  getTestCases, 
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

  const activeTestCase = testCases.find(t => t.id === activeTestCaseId) || testCases[0];

  // Check backend health & fetch live data on load
  useEffect(() => {
    async function initPlatform() {
      const health = await checkBackendHealth();
      if (health && health.status === 'healthy') {
        setBackendStatus(true);
        const liveCases = await getTestCases();
        if (liveCases && liveCases.length > 0) {
          // Merge live test cases with sample rich data
          const merged = liveCases.map((lc, idx) => ({
            id: lc.external_id || `TC-${lc.id}`,
            name: lc.name,
            category: lc.category || 'Functional',
            priority: lc.priority || 'High',
            version: `${lc.version || 1}.0`,
            outcome: idx % 3 === 0 ? 'HEALED' : (idx % 3 === 1 ? 'PASSED' : 'FAILED'),
            duration: `${Math.floor(Math.random() * 2) + 1}m ${Math.floor(Math.random() * 50) + 10}s`,
            logs: DEFAULT_TEST_CASES[0].logs,
            failure: DEFAULT_TEST_CASES[0].failure,
            healing: DEFAULT_TEST_CASES[0].healing,
          }));
          setTestCases([...merged, ...DEFAULT_TEST_CASES]);
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
      name: result.test_case_name || 'Autonomous Flow Execution',
      category: 'Autonomous',
      priority: 'High',
      version: '1.0',
      outcome: result.status || 'PASSED',
      duration: `${result.duration_ms ? (result.duration_ms / 1000).toFixed(1) + 's' : '2.4s'}`,
      logs: (result.events || []).map(e => ({
        time: new Date().toLocaleTimeString('en-US', { hour12: false }),
        text: `[${e.event_type}] ${e.message}`,
        type: e.event_type.includes('COMPLETED') ? 'success' : 'agent',
      })),
      failure: DEFAULT_TEST_CASES[0].failure,
      healing: DEFAULT_TEST_CASES[0].healing,
    };

    setTestCases([newCase, ...testCases]);
    setActiveTestCaseId(newId);
    setTimerSeconds(0);
    setCurrentStepIndex(5); // Completed (Persist)

    // If result has execution_id, subscribe to SSE stream
    if (result.execution_id) {
      subscribeToWorkflowStream(
        result.execution_id,
        (event) => {
          console.log('Live SSE Event:', event);
        },
        (err) => {
          console.log('Stream ended or closed.');
        }
      );
    }
  }

  function handleSelectTestCase(id) {
    setActiveTestCaseId(id);
    const tc = testCases.find(t => t.id === id);
    if (!tc) return;

    // Set stepper state based on outcome
    if (tc.outcome === 'HEALED') setCurrentStepIndex(3); // HEAL
    else if (tc.outcome === 'PASSED') setCurrentStepIndex(5); // PERSIST
    else setCurrentStepIndex(2); // DIAGNOSE
  }

  function handleRunTest(tc) {
    handleSelectTestCase(tc.id);
    setTimerSeconds(0);
    setIsRunning(true);
    setCurrentStepIndex(0); // PLAN

    // Animate stepper through stages
    setTimeout(() => setCurrentStepIndex(1), 600); // EXECUTE
    setTimeout(() => {
      if (tc.outcome === 'HEALED') {
        setCurrentStepIndex(2); // DIAGNOSE
        setTimeout(() => setCurrentStepIndex(3), 800); // HEAL
        setTimeout(() => setCurrentStepIndex(4), 1600); // VALIDATE
        setTimeout(() => setCurrentStepIndex(5), 2400); // PERSIST
      } else if (tc.outcome === 'PASSED') {
        setTimeout(() => setCurrentStepIndex(5), 1200); // PERSIST
      } else {
        setCurrentStepIndex(2); // DIAGNOSE
      }
    }, 1200);
  }

  return (
    <div className="app-layout">
      <Sidebar 
        activeNav={activeNav} 
        setActiveNav={setActiveNav}
        backendStatus={backendStatus}
        onNewRunClick={() => setIsModalOpen(true)}
      />

      <div className="main-content">
        <Header 
          searchQuery={searchQuery}
          setSearchQuery={setSearchQuery}
          onNewRunClick={() => setIsModalOpen(true)}
          backendStatus={backendStatus}
        />

        <main className="content-container">
          <MetricsOverview stats={{
            totalTests: testCases.length,
            passRate: 97.4,
            healedCount: testCases.filter(c => c.outcome === 'HEALED').length,
            avgDuration: '1.45s',
          }} />

          <PipelineStepper 
            currentStepIndex={currentStepIndex}
            onStepClick={(index) => setCurrentStepIndex(index)}
          />

          <LiveExecutionConsole 
            activeRun={activeTestCase}
            logs={activeTestCase?.logs || []}
            timerSeconds={timerSeconds}
            isRunning={isRunning}
            onTogglePlay={() => setIsRunning(!isRunning)}
            onReset={() => handleRunTest(activeTestCase)}
          />

          <TestCaseTable 
            testCases={testCases}
            activeTestCaseId={activeTestCaseId}
            onSelectTestCase={handleSelectTestCase}
            onRunTest={handleRunTest}
          />
        </main>
      </div>

      <PlanExecuteModal 
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onExecutionStarted={handleExecutionStarted}
      />
    </div>
  );
}
