/**
 * TestSphere-AI — API Client & Telemetry Stream Bridge
 */

function getApiBase() {
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL.replace(/\/$/, '');
  }
  if (typeof window !== 'undefined') {
    // If the browser is on port 8000 or Vite dev server on port 3000 with proxy
    if (window.location.port === '8000' || window.location.port === '3000') {
      return '';
    }
  }
  // Otherwise, default directly to the FastAPI backend running on 127.0.0.1:8000
  return 'http://127.0.0.1:8000';
}

const BASE_URL = getApiBase();

/**
 * Fetch with automatic fallback directly to http://127.0.0.1:8000
 */
async function fetchWithFallback(endpoint, options = {}) {
  const url = `${BASE_URL}${endpoint}`;
  try {
    const res = await fetch(url, options);
    if (res.ok) return res;
  } catch (err) {
    if (!url.startsWith('http://127.0.0.1:8000')) {
      const fallbackUrl = `http://127.0.0.1:8000${endpoint}`;
      try {
        const res2 = await fetch(fallbackUrl, options);
        if (res2.ok) return res2;
      } catch (err2) {
        throw err2;
      }
    }
    throw err;
  }
  // If response not ok, try fallback
  if (!url.startsWith('http://127.0.0.1:8000')) {
    try {
      const fallbackUrl = `http://127.0.0.1:8000${endpoint}`;
      const res2 = await fetch(fallbackUrl, options);
      if (res2.ok) return res2;
    } catch {
      // ignore
    }
  }
  return await fetch(url, options);
}

export async function checkBackendHealth() {
  try {
    const res = await fetchWithFallback('/api/health');
    if (!res.ok) throw new Error(`Health check returned status ${res.status}`);
    const data = await res.json();
    return data;
  } catch (err) {
    console.warn('Backend health check offline:', err.message);
    return null;
  }
}

export async function getProjects() {
  try {
    const res = await fetchWithFallback('/api/projects');
    if (!res.ok) throw new Error(`Failed to fetch projects`);
    return await res.json();
  } catch (err) {
    console.warn('Error fetching projects:', err.message);
    return [];
  }
}

export async function createProject(payload) {
  const res = await fetchWithFallback('/api/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error('Failed to create project');
  return await res.json();
}

export async function getApplications(projectId = null) {
  try {
    const endpoint = projectId 
      ? `/api/applications?project_id=${projectId}` 
      : `/api/applications`;
    const res = await fetchWithFallback(endpoint);
    if (!res.ok) throw new Error(`Failed to fetch applications`);
    return await res.json();
  } catch (err) {
    console.warn('Error fetching applications:', err.message);
    return [];
  }
}

export async function createApplication(payload) {
  const res = await fetchWithFallback('/api/applications', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error('Failed to create application');
  return await res.json();
}

export async function getTestCases(appId = null) {
  try {
    const endpoint = appId 
      ? `/api/test-cases?application_id=${appId}` 
      : `/api/test-cases`;
    const res = await fetchWithFallback(endpoint);
    if (!res.ok) throw new Error(`Failed to fetch test cases`);
    return await res.json();
  } catch (err) {
    console.warn('Error fetching test cases:', err.message);
    return [];
  }
}

export async function getTestExecutions() {
  try {
    const res = await fetchWithFallback('/api/test-executions');
    if (!res.ok) throw new Error(`Failed to fetch test executions`);
    return await res.json();
  } catch (err) {
    console.warn('Error fetching test executions:', err.message);
    return [];
  }
}

export async function planAndExecuteWorkflow(payload) {
  const res = await fetchWithFallback('/api/workflow/plan-and-execute', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || `Execution failed with status ${res.status}`);
  }

  return await res.json();
}

export async function analyzeWebsiteUrl(url, prompt = null, testCaseName = null) {
  const res = await fetchWithFallback('/api/workflow/analyze', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      url,
      prompt,
      test_case_name: testCaseName,
    }),
  });

  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || `Analysis failed with status ${res.status}`);
  }

  return await res.json();
}

export function subscribeToWorkflowStream(workflowId, onEvent, onError) {
  const sseBase = BASE_URL || 'http://127.0.0.1:8000';
  const sseUrl = `${sseBase}/api/workflow/stream/${workflowId}`;
  const eventSource = new EventSource(sseUrl);

  const eventTypes = [
    'WORKFLOW_STARTED',
    'TEST_PLAN_GENERATED',
    'EXECUTION_RESULT_RECEIVED',
    'FAILURE_ANALYSIS_COMPLETED',
    'CANDIDATES_GENERATED',
    'CANDIDATES_RANKED',
    'HEALING_DECISION_CREATED',
    'HEALING_RECOMMENDATION_SENT',
    'HEALING_RESULT_RECEIVED',
    'WORKFLOW_COMPLETED',
    'STATE_TRANSITION',
    'ping'
  ];

  eventTypes.forEach(type => {
    eventSource.addEventListener(type, (e) => {
      try {
        const parsed = JSON.parse(e.data);
        onEvent({ type, data: parsed });
      } catch {
        onEvent({ type, data: e.data });
      }
    });
  });

  eventSource.onmessage = (e) => {
    try {
      const parsed = JSON.parse(e.data);
      onEvent({ type: 'message', data: parsed });
    } catch {
      onEvent({ type: 'message', data: e.data });
    }
  };

  eventSource.onerror = (err) => {
    if (onError) onError(err);
    eventSource.close();
  };

  return () => {
    eventSource.close();
  };
}
