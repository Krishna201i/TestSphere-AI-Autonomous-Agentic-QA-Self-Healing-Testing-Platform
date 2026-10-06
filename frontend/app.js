/**
 * TestSphere-AI — Autonomous Agentic QA Platform Dashboard
 * Interactive Controller, Real-Time Stepper, Log Streamer & API Bridge
 */

// --- Global State & Configuration ---
const API_BASE_URL = window.location.origin.includes(':8000') 
  ? window.location.origin 
  : 'http://localhost:8000';

let currentExecutionState = {
  isRunning: true,
  timerSeconds: 78, // 1m 18s initial
  timerInterval: null,
  currentStepIndex: 1, // EXECUTE active
  activeTestCaseId: 'TC_LOGIN_001',
  activeExecutionId: 'exec_20250429_102432',
};

const STEP_SEQUENCE = ['plan', 'execute', 'diagnose', 'heal', 'validate', 'persist'];

// Test Case mock definitions for interactive simulations
const TEST_CASES_DATA = {
  TC_LOGIN_001: {
    id: 'TC_LOGIN_001',
    name: 'User Login',
    category: 'Functional',
    priority: 'High',
    version: '1.0',
    outcome: 'HEALED',
    duration: '2m 34s',
    logs: [
      { time: '10:24:03', text: 'Starting test execution for test case: TC_LOGIN_001', type: 'info' },
      { time: '10:24:05', text: 'Navigating to https://example.com/login', type: 'default' },
      { time: '10:24:12', text: 'Waiting for page to load...', type: 'default' },
      { time: '10:24:18', text: 'Entering username and password...', type: 'default' },
      { time: '10:24:25', text: 'Clicked on login button (#login-btn)', type: 'default' },
      { time: '10:24:28', text: 'Locator timeout: #login-btn not found. Triggering Failure Analyzer Agent...', type: 'warn' },
      { time: '10:24:30', text: 'AI Agent diagnosed LOCATOR_CHANGED (Confidence: 92%)', type: 'info' },
      { time: '10:24:32', text: 'Candidate selector synthesized: button[type="submit"]', type: 'info' },
      { time: '10:24:35', text: 'Playwright engine validating replacement in isolated context...', type: 'default' },
      { time: '10:24:38', text: 'Validation SUCCESS! Test step healed and state persisted to DB.', type: 'success' }
    ],
    failure: {
      category: 'Element Not Found',
      rootCause: 'Login button selector changed',
      details: "Element with selector '#login-btn' not found on the page",
      evidenceImg: 'assets/evidence_preview.jpg'
    },
    healing: {
      candidate: 'CSS Selector Update',
      confidence: '92%',
      oldSelector: '#login-btn',
      newSelector: 'button[type="submit"]',
      validation: 'Successfully validated by browser',
      status: 'Healing Successful'
    }
  },
  TC_CART_002: {
    id: 'TC_CART_002',
    name: 'Add to Cart',
    category: 'Functional',
    priority: 'High',
    version: '1.0',
    outcome: 'FAILED',
    duration: '1m 12s',
    logs: [
      { time: '10:12:00', text: 'Starting test execution for test case: TC_CART_002', type: 'info' },
      { time: '10:12:04', text: 'Navigating to https://example.com/products/item-42', type: 'default' },
      { time: '10:12:08', text: 'Clicking button[data-testid="add-to-cart"]', type: 'default' },
      { time: '10:12:12', text: 'Server returned HTTP 500 Internal Server Error', type: 'error' },
      { time: '10:12:14', text: 'Failure categorized as APPLICATION_BUG. Non-healable.', type: 'error' }
    ],
    failure: {
      category: 'API 500 Error',
      rootCause: 'Backend cart service exception during checkout',
      details: 'HTTP 500 Internal Server Error received from /api/cart/add',
      evidenceImg: 'assets/evidence_preview.jpg'
    },
    healing: {
      candidate: 'None (Application Bug)',
      confidence: '0%',
      oldSelector: 'N/A',
      newSelector: 'N/A',
      validation: 'Self-healing aborted — true app regression',
      status: 'Heal Skipped (Bug)'
    }
  },
  TC_CHECKOUT_003: {
    id: 'TC_CHECKOUT_003',
    name: 'Checkout Flow',
    category: 'Functional',
    priority: 'Medium',
    version: '1.0',
    outcome: 'PASSED',
    duration: '3m 18s',
    logs: [
      { time: '09:58:10', text: 'Starting test execution for test case: TC_CHECKOUT_003', type: 'info' },
      { time: '09:58:15', text: 'Navigating to https://example.com/checkout', type: 'default' },
      { time: '09:58:25', text: 'Filling shipping and payment form details...', type: 'default' },
      { time: '09:58:35', text: 'Submitting payment order #ord-9821', type: 'default' },
      { time: '09:58:43', text: 'Order confirmation received. All assertions passed.', type: 'success' }
    ],
    failure: {
      category: 'None',
      rootCause: 'All steps executed deterministically',
      details: 'No locator drift or application assertion errors detected.',
      evidenceImg: 'assets/evidence_preview.jpg'
    },
    healing: {
      candidate: 'Not Needed',
      confidence: '100%',
      oldSelector: 'N/A',
      newSelector: 'N/A',
      validation: 'Original locators validated successfully',
      status: 'Test Passed Cleanly'
    }
  }
};

// --- Initialization ---
document.addEventListener('DOMContentLoaded', () => {
  initClock();
  initExecutionTimer();
  initInteractiveStepper();
  initTableActionButtons();
  initSearchFilter();
  initStopResumeButton();
  tryConnectBackendHealth();
});

// --- Digital Clock in Header ---
function initClock() {
  const clockEl = document.getElementById('live-clock');
  function updateClock() {
    const now = new Date();
    const options = { weekday: 'long', year: 'numeric', month: 'short', day: 'numeric' };
    const dateStr = now.toLocaleDateString('en-US', options);
    const timeStr = now.toLocaleTimeString('en-US', { hour12: true });
    if (clockEl) {
      clockEl.textContent = `${dateStr} | ${timeStr}`;
    }
  }
  updateClock();
  setInterval(updateClock, 1000);
}

// --- Live Execution Elapsed Timer ---
function initExecutionTimer() {
  const timerEl = document.getElementById('execution-timer');
  
  function formatSeconds(sec) {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}m ${s < 10 ? '0' : ''}${s}s`;
  }

  currentExecutionState.timerInterval = setInterval(() => {
    if (currentExecutionState.isRunning) {
      currentExecutionState.timerSeconds++;
      if (timerEl) {
        timerEl.textContent = formatSeconds(currentExecutionState.timerSeconds);
      }
    }
  }, 1000);
}

// --- Stepper Pipeline Navigation ---
function initInteractiveStepper() {
  const stepperContainer = document.getElementById('pipeline-stepper');
  if (!stepperContainer) return;

  const nodes = stepperContainer.querySelectorAll('.stepper-node');
  const connectors = stepperContainer.querySelectorAll('.stepper-connector');

  nodes.forEach((node, index) => {
    node.addEventListener('click', () => {
      setStepperStep(index);
    });
  });
}

function setStepperStep(targetIndex) {
  currentExecutionState.currentStepIndex = targetIndex;
  const nodes = document.querySelectorAll('.stepper-node');
  const connectors = document.querySelectorAll('.stepper-connector');

  nodes.forEach((node, idx) => {
    node.classList.remove('active', 'completed');
    if (idx < targetIndex) {
      node.classList.add('completed');
    } else if (idx === targetIndex) {
      node.classList.add('active');
    }
  });

  connectors.forEach((conn, idx) => {
    if (idx < targetIndex) {
      conn.classList.add('active');
    } else {
      conn.classList.remove('active');
    }
  });
}

// --- Stop / Resume Toggle Button ---
function initStopResumeButton() {
  const btn = document.getElementById('btn-toggle-execution');
  const statusPill = document.getElementById('live-status-pill');
  const statusText = document.getElementById('live-status-text');
  const btnText = document.getElementById('btn-stop-text');

  if (!btn) return;

  btn.addEventListener('click', () => {
    currentExecutionState.isRunning = !currentExecutionState.isRunning;

    if (currentExecutionState.isRunning) {
      btnText.textContent = 'Stop';
      btn.style.background = 'rgba(239, 68, 68, 0.15)';
      btn.style.color = '#f87171';
      statusText.textContent = 'Execution in Progress';
      statusPill.style.background = 'rgba(16, 185, 129, 0.15)';
      statusPill.style.color = '#34d399';
    } else {
      btnText.textContent = 'Resume';
      btn.style.background = 'rgba(16, 185, 129, 0.2)';
      btn.style.color = '#34d399';
      statusText.textContent = 'Execution Paused';
      statusPill.style.background = 'rgba(245, 158, 11, 0.15)';
      statusPill.style.color = '#fbbf24';
    }
  });
}

// --- Table Action "Run" Buttons ---
function initTableActionButtons() {
  // Test Cases table Run buttons
  const runButtons = document.querySelectorAll('[data-run]');
  runButtons.forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const tcId = btn.getAttribute('data-run');
      triggerTestCaseRun(tcId);
    });
  });

  // Recent Executions row clicks
  const execRows = document.querySelectorAll('#executions-tbody tr');
  execRows.forEach(row => {
    row.addEventListener('click', () => {
      const execId = row.getAttribute('data-exec-id');
      const tcCell = row.children[1].textContent.trim();
      triggerTestCaseRun(tcCell, execId);
    });
  });

  // Test Cases row clicks
  const tcRows = document.querySelectorAll('#test-cases-tbody tr');
  tcRows.forEach(row => {
    row.addEventListener('click', () => {
      const tcId = row.getAttribute('data-tc-id');
      triggerTestCaseRun(tcId);
    });
  });
}

// --- Trigger Test Case Run Simulation ---
function triggerTestCaseRun(testCaseId, customExecId = null) {
  const data = TEST_CASES_DATA[testCaseId] || TEST_CASES_DATA.TC_LOGIN_001;

  // Update Execution metadata
  const execId = customExecId || `exec_${new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14)}`;
  currentExecutionState.activeExecutionId = execId;
  currentExecutionState.activeTestCaseId = testCaseId;
  currentExecutionState.timerSeconds = 0;
  currentExecutionState.isRunning = true;

  const execIdEl = document.getElementById('current-exec-id');
  if (execIdEl) execIdEl.textContent = execId;

  // Animate Stepper
  setStepperStep(0); // PLAN

  // Stream Logs into Terminal
  const terminalEl = document.getElementById('terminal-logs');
  if (terminalEl) {
    terminalEl.innerHTML = '';
    
    data.logs.forEach((logItem, index) => {
      setTimeout(() => {
        const line = document.createElement('div');
        line.className = 'log-line';
        line.innerHTML = `<span class="log-time">[${logItem.time}]</span><span class="log-text ${logItem.type}">${logItem.text}</span>`;
        terminalEl.appendChild(line);
        terminalEl.scrollTop = terminalEl.scrollHeight;

        // Advance stepper based on log sequence
        if (index === 1) setStepperStep(1); // EXECUTE
        if (index === 5) setStepperStep(2); // DIAGNOSE
        if (index === 7) setStepperStep(3); // HEAL
        if (index === 8) setStepperStep(4); // VALIDATE
        if (index === 9) setStepperStep(5); // PERSIST
      }, index * 400);
    });
  }

  // Update Diagnostics Panels
  updateDiagnosticsPanel(data);
}

// --- Update Diagnostics (Failure & Healing) ---
function updateDiagnosticsPanel(data) {
  // Failure Card
  const failureCategory = document.getElementById('failure-category');
  const failureRoot = document.getElementById('failure-root-cause');
  const failureDetails = document.getElementById('failure-details');
  const failureBadge = document.getElementById('failure-status-badge');

  if (failureCategory) failureCategory.textContent = data.failure.category;
  if (failureRoot) failureRoot.textContent = data.failure.rootCause;
  if (failureDetails) failureDetails.textContent = data.failure.details;
  if (failureBadge) {
    failureBadge.textContent = data.outcome;
    if (data.outcome === 'PASSED') {
      failureBadge.className = 'pill-badge green';
      failureBadge.style.background = 'rgba(16, 185, 129, 0.2)';
      failureBadge.style.color = '#34d399';
    } else {
      failureBadge.className = 'pill-badge red';
      failureBadge.style.background = 'rgba(244, 63, 94, 0.2)';
      failureBadge.style.color = '#f43f5e';
    }
  }

  // Healing Card
  const healCandidate = document.getElementById('healing-candidate');
  const healConfidence = document.getElementById('healing-confidence');
  const confidenceFill = document.getElementById('confidence-fill');
  const healOldSel = document.getElementById('healing-old-selector');
  const healNewSel = document.getElementById('healing-new-selector');
  const healValidation = document.getElementById('healing-validation');
  const healOutcome = document.getElementById('healing-outcome-text');

  if (healCandidate) healCandidate.textContent = data.healing.candidate;
  if (healConfidence) healConfidence.textContent = data.healing.confidence;
  if (confidenceFill) confidenceFill.style.width = data.healing.confidence;
  if (healOldSel) healOldSel.textContent = data.healing.oldSelector;
  if (healNewSel) healNewSel.textContent = data.healing.newSelector;
  if (healValidation) healValidation.textContent = data.healing.validation;
  if (healOutcome) healOutcome.textContent = data.healing.status;
}

// --- Real-Time Search Filter ---
function initSearchFilter() {
  const searchInput = document.getElementById('global-search');
  if (!searchInput) return;

  searchInput.addEventListener('input', (e) => {
    const query = e.target.value.toLowerCase().trim();
    const rows = document.querySelectorAll('#test-cases-tbody tr');

    rows.forEach(row => {
      const text = row.textContent.toLowerCase();
      if (text.includes(query)) {
        row.style.display = '';
      } else {
        row.style.display = 'none';
      }
    });
  });

  // Ctrl+K keyboard shortcut focus
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      searchInput.focus();
    }
  });
}

// --- Optional Backend Live Probe ---
async function tryConnectBackendHealth() {
  try {
    const res = await fetch(`${API_BASE_URL}/api/health`, { method: 'GET' });
    if (res.ok) {
      console.log('✅ Connected to TestSphere-AI Backend API:', API_BASE_URL);
      
      // Optionally fetch live test cases
      const tcRes = await fetch(`${API_BASE_URL}/api/test-cases`);
      if (tcRes.ok) {
        const liveCases = await tcRes.json();
        console.log('Loaded live test cases from DB:', liveCases);
      }
    }
  } catch (err) {
    console.log('Running in standalone simulated mode (FastAPI backend offline).');
  }
}
