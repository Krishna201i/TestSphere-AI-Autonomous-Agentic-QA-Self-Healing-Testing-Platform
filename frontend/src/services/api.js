/**
 * TestSphere-AI — API Client & Telemetry Stream Bridge
 */

const BASE_URL = import.meta.env.VITE_API_URL 
  ? import.meta.env.VITE_API_URL.replace(/\/$/, '')
  : (typeof window !== 'undefined' && window.location.port === '3000' 
      ? '' 
      : (typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8000'));

export async function checkBackendHealth() {
  try {
    const res = await fetch(`${BASE_URL}/api/health`);
    if (!res.ok) throw new Error(`Health check returned status ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn('Backend health check offline:', err.message);
    return null;
  }
}

export async function getProjects() {
  try {
    const res = await fetch(`${BASE_URL}/api/projects`);
    if (!res.ok) throw new Error(`Failed to fetch projects`);
    return await res.json();
  } catch (err) {
    console.warn('Error fetching projects:', err.message);
    return [];
  }
}

export async function getApplications(projectId = null) {
  try {
    const url = projectId 
      ? `${BASE_URL}/api/applications?project_id=${projectId}` 
      : `${BASE_URL}/api/applications`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Failed to fetch applications`);
    return await res.json();
  } catch (err) {
    console.warn('Error fetching applications:', err.message);
    return [];
  }
}

export async function getTestCases(appId = null) {
  try {
    const url = appId 
      ? `${BASE_URL}/api/test-cases?application_id=${appId}` 
      : `${BASE_URL}/api/test-cases`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Failed to fetch test cases`);
    return await res.json();
  } catch (err) {
    console.warn('Error fetching test cases:', err.message);
    return [];
  }
}

export async function getTestExecutions() {
  try {
    const res = await fetch(`${BASE_URL}/api/test-executions`);
    if (!res.ok) throw new Error(`Failed to fetch test executions`);
    return await res.json();
  } catch (err) {
    console.warn('Error fetching test executions:', err.message);
    return [];
  }
}

export async function planAndExecuteWorkflow(payload) {
  const res = await fetch(`${BASE_URL}/api/workflow/plan-and-execute`, {
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

export function subscribeToWorkflowStream(workflowId, onEvent, onError) {
  const sseUrl = `${BASE_URL}/api/workflow/stream/${workflowId}`;
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
