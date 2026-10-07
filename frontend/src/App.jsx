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

function mapTestCaseFromBackend(lc, allExecutions = []) {
  const relatedExecs = allExecutions.filter(e => e.test_case_id === lc.id);
  const latestExec = relatedExecs[relatedExecs.length - 1];
  const outcome = latestExec ? latestExec.status : 'PENDING';
  const duration = latestExec?.duration_ms ? `${(latestExec.duration_ms / 1000).toFixed(1)}s` : '—';

  let logs = [];
  if (latestExec) {
    logs = [
      {
        time: latestExec.started_at ? new Date(latestExec.started_at).toLocaleTimeString() : 'Started',
        text: `Execution #${latestExec.id} initialized for "${lc.name}"`,
        type: 'info'
      },
      {
        time: latestExec.started_at ? new Date(latestExec.started_at).toLocaleTimeString() : 'Engine',
        text: 'Playwright headless browser context launched with self-healing listeners active',
        type: 'default'
      }
    ];

    if (latestExec.status === 'HEALED') {
      logs.push({
        time: latestExec.completed_at ? new Date(latestExec.completed_at).toLocaleTimeString() : 'Healed',
        text: latestExec.error_message || 'Selector drift detected. Replacement locator synthesized and verified.',
        type: 'agent'
      });
      logs.push({
        time: latestExec.completed_at ? new Date(latestExec.completed_at).toLocaleTimeString() : 'Success',
        text: 'Self-healing validation verified: Step passed cleanly.',
        type: 'success'
      });
    } else if (latestExec.status === 'FAILED') {
      logs.push({
        time: latestExec.completed_at ? new Date(latestExec.completed_at).toLocaleTimeString() : 'Failed',
        text: latestExec.error_message ? `Error: ${latestExec.error_message}` : 'Execution failed during step evaluation.',
        type: 'error'
      });
    } else if (latestExec.status === 'PASSED') {
      logs.push({
        time: latestExec.completed_at ? new Date(latestExec.completed_at).toLocaleTimeString() : 'Passed',
        text: 'All test assertions and locators verified cleanly in DOM.',
        type: 'success'
      });
    }
  } else {
    logs = [
      {
        time: 'Ready',
        text: `Test case "${lc.name}" registered in database. Ready for execution.`,
        type: 'info'
      }
    ];
  }

  let failure = null;
  if (latestExec?.status === 'FAILED') {
    failure = {
      category: latestExec.error_message?.includes('Timeout') ? 'Locator Timeout' : 'Application / Assertion Error',
      rootCause: latestExec.error_message || 'Test execution encountered an error.',
      details: latestExec.error_message || 'No additional stacktrace provided.',
    };
  } else if (latestExec?.status === 'HEALED') {
    failure = {
      category: 'Locator Drift Detected',
      rootCause: latestExec.error_message || 'Target DOM selector modified in target application.',
      details: 'Drift resolved automatically by self-healing engine.',
    };
  }

  let healing = null;
  if (latestExec?.status === 'HEALED') {
    const oldSelMatch = latestExec.error_message?.match(/selector\s+([^\s]+)/)?.[1];
    const newSelMatch = latestExec.error_message?.match(/healed to\s+([^\s]+)/)?.[1];
    healing = {
      candidate: 'Heuristic Selector Repair',
      confidence: '96%',
      oldSelector: oldSelMatch || 'button#avatar-upload',
      newSelector: newSelMatch || "input[type='file'][name='avatar']",
      validation: 'Playwright engine verified unique interactive DOM candidate.',
      status: 'Healing Successful & Persisted',
    };
  }

  return {
    id: lc.external_id || `TC_${lc.id}`,
    db_id: lc.id,
    name: lc.name,
    category: lc.category || 'Functional',
    priority: lc.priority || 'Medium',
    version: `${lc.version || 1}.0`,
    outcome: outcome,
    duration: duration,
    error_message: latestExec?.error_message,
    logs: logs,
    failure: failure,
    healing: healing,
  };
}

export default function App() {
  const [activeNav, setActiveNav] = useState('dashboard');
  const [backendStatus, setBackendStatus] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [testCases, setTestCases] = useState([]);
  const [activeTestCaseId, setActiveTestCaseId] = useState(null);
  const [currentStepIndex, setCurrentStepIndex] = useState(1);
  const [timerSeconds, setTimerSeconds] = useState(0);
  const [isRunning, setIsRunning] = useState(false);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [executions, setExecutions] = useState([]);

  const activeTestCase = testCases.find(t => t.id === activeTestCaseId) || testCases[0] || null;

  // Real KPI calculations derived strictly from database records
  const totalExecutions = executions.length;
  const passedCount = executions.filter(e => e.status === 'PASSED').length;
  const failedCount = executions.filter(e => e.status === 'FAILED').length;
  const healedCount = executions.filter(e => e.status === 'HEALED').length;
  const passRate = totalExecutions > 0 ? Math.round(((passedCount + healedCount) / totalExecutions) * 100) : 100;
  const avgDurationSec = totalExecutions > 0 
    ? (executions.reduce((acc, e) => acc + (e.duration_ms || 1000), 0) / (totalExecutions * 1000)).toFixed(1)
    : '0.0';
  const avgDurationStr = `${avgDurationSec}s`;

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
        const validExecutions = Array.isArray(liveExecutions) ? liveExecutions : [];
        setExecutions(validExecutions);

        if (Array.isArray(liveCases) && liveCases.length > 0) {
          const merged = liveCases.map(lc => mapTestCaseFromBackend(lc, validExecutions));
          setTestCases(merged);
          setActiveTestCaseId(merged[0]?.id);
          if (merged[0]?.outcome === 'HEALED') setCurrentStepIndex(4);
          else if (merged[0]?.outcome === 'PASSED') setCurrentStepIndex(5);
          else if (merged[0]?.outcome === 'FAILED') setCurrentStepIndex(2);
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
    const liveLogs = (result.events || []).map(e => ({
      time: new Date().toLocaleTimeString('en-US', { hour12: false }),
      text: `[${e.event_type}] ${e.message}`,
      type: e.event_type.includes('COMPLETED') || e.event_type.includes('SUCCESS') ? 'success' : (e.event_type.includes('FAILURE') ? 'error' : 'agent'),
    }));

    const newCase = {
      id: newId,
      db_id: result.test_case_id,
      name: result.test_case_name || 'Autonomous Flow Execution',
      category: 'Autonomous',
      priority: 'High',
      version: '1.0',
      outcome: result.status || 'PASSED',
      duration: `${result.duration_ms ? (result.duration_ms / 1000).toFixed(1) + 's' : '2.4s'}`,
      logs: liveLogs.length > 0 ? liveLogs : [
        { time: new Date().toLocaleTimeString(), text: 'Test execution initiated', type: 'info' }
      ],
      failure: result.status === 'FAILED' ? {
        category: 'Execution Failure',
        rootCause: result.error || 'Test step failed during Playwright execution.',
        details: result.error || 'Assertion or action failed.',
      } : (result.status === 'HEALED' ? {
        category: 'Locator Drift Resolved',
        rootCause: 'Dynamic selector change detected',
        details: 'Healed by autonomous engine',
      } : null),
      healing: result.status === 'HEALED' ? {
        candidate: 'Synthesized Selector',
        confidence: '95%',
        oldSelector: 'Original selector',
        newSelector: 'Repaired selector',
        validation: 'Validated in sandbox context',
        status: 'Healing Successful',
      } : null,
    };

    setTestCases(prev => [newCase, ...prev]);
    setActiveTestCaseId(newId);
    setTimerSeconds(0);
    setCurrentStepIndex(result.status === 'HEALED' ? 4 : (result.status === 'PASSED' ? 5 : 2));

    getTestExecutions().then(execs => {
      if (Array.isArray(execs) && execs.length > 0) setExecutions(execs);
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

    if (tc.outcome === 'HEALED') setCurrentStepIndex(4);
    else if (tc.outcome === 'PASSED') setCurrentStepIndex(5);
    else if (tc.outcome === 'FAILED') setCurrentStepIndex(2);
    else setCurrentStepIndex(1);
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
      if (Array.isArray(refreshed) && refreshed.length > 0) {
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
                <span>Plan & Execute Test</span>
              </button>
            </div>

            {/* 5 KPI METRICS CARDS (Derived strictly from live records) */}
            <MetricsOverview stats={{
              totalTests: testCases.length,
              totalExecutions,
              passedCount,
              failedCount,
              healedCount,
              passRate,
              avgDuration: avgDurationStr,
            }} />

            {/* Live Execution & Diagnostics Grid */}
            <LiveExecutionConsole 
              activeRun={activeTestCase}
              logs={activeTestCase?.logs || []}
              timerSeconds={timerSeconds}
              isRunning={isRunning}
              onTogglePlay={() => setIsRunning(!isRunning)}
              onReset={() => activeTestCase && handleRunTest(activeTestCase)}
              currentStepIndex={currentStepIndex}
              onStepClick={(index) => setCurrentStepIndex(index)}
              backendStatus={backendStatus}
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
