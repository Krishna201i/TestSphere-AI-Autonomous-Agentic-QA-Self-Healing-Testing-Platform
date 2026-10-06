# TestSphere-AI End-to-End Integration & Developer Guide

## 1. System Integration Overview

TestSphere-AI unifies three distinct architectural domains into a unified QA automation platform:

1. **Member 1: AI Agent & Intelligence Layer** ([`agents/`](file:///agents/))
   - Synthesizes comprehensive test plans from natural language app descriptions and DOM trees.
   - Diagnoses failure roots and invents resilient locator candidates.
2. **Member 2: Browser Execution Engine** ([`engine/`](file:///engine/))
   - Executes test actions deterministically on real Chromium/Firefox/WebKit browsers.
   - Captures screenshots, DOM state dumps, and execution timings.
3. **Member 3: Platform Backend & APIs** ([`backend/`](file:///backend/))
   - Manages relational state (projects, test cases, executions) in PostgreSQL / SQLite.
   - Exposes REST APIs, orchestration pipelines, and real-time SSE streams.

---

## 2. LLM Provider Flexibility: Mock vs Production

TestSphere-AI features an offline-first design. All 1,102 automated tests run offline with **zero external API calls and zero costs**.

### 2.1 Offline Mode (`LLM_PROVIDER=mock`)
Default setting out of the box. Utilizes registered scenario providers (`agents/planner/mock_scenarios.py`) simulating realistic LLM responses:
```bash
# In .env:
LLM_PROVIDER=mock
LLM_MOCK_SCENARIO=standard_ecommerce
```
- Completely deterministic.
- Instant execution with zero latency.
- Simulates edge cases: hallucinated selectors, duplicate tests, unexpected token drops, and recovery failures.

### 2.2 Production AI Providers
Switch to cloud LLM providers simply by setting environment variables in `.env`:

```ini
# OpenAI
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-4o

# Anthropic Claude
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
LLM_MODEL=claude-3-5-sonnet-20241022

# Google Gemini
LLM_PROVIDER=gemini
GEMINI_API_KEY=AIzaSy...
LLM_MODEL=gemini-1.5-pro
```

---

## 3. Programmatic Invocation Example (Python)

You can invoke the entire autonomous QA pipeline programmatically in Python:

```python
import asyncio
from backend.database.session import get_db_session
from backend.orchestration.orchestrator import PlatformWorkflowOrchestrator
from agents.planner.schemas import ApplicationContext, PageElement

async def run_autonomous_qa():
    # 1. Define application context
    app_context = ApplicationContext(
        app_name="Acme Store",
        base_url="https://demo.testfire.net",
        description="E-commerce login and checkout portal",
        elements=[
            PageElement(id="username", tag="input", attributes={"type": "text", "name": "uid"}),
            PageElement(id="password", tag="input", attributes={"type": "password", "name": "passw"}),
            PageElement(id="login_btn", tag="button", attributes={"type": "submit", "name": "btnSubmit"}),
        ]
    )

    # 2. Initialize orchestrator with database session
    with get_db_session() as db:
        orchestrator = PlatformWorkflowOrchestrator(db_session=db)
        
        # 3. Stream workflow events in real time
        async for event in orchestrator.execute_workflow_stream(app_context=app_context):
            print(f"[{event.event_type}] {event.message}")
            if event.screenshot_url:
                print(f"  Screenshot: {event.screenshot_url}")

if __name__ == "__main__":
    asyncio.run(run_autonomous_qa())
```

---

## 4. REST API & SSE Consumption

### 4.1 Triggering Workflow via HTTP
```bash
curl -X POST http://localhost:8000/api/workflow/plan-and-execute \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": 1,
    "app_name": "Demo App",
    "base_url": "https://example.com",
    "description": "User registration and settings dashboard"
  }'
```

### 4.2 Consuming Real-Time SSE Stream (JavaScript / React)
```javascript
const eventSource = new EventSource("http://localhost:8000/api/workflow/stream/exec_123");

eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log("Status:", data.step_name, data.status);
  
  if (data.is_healed) {
    console.warn("Self-healing triggered! New selector:", data.healed_selector);
  }
};

eventSource.onerror = (err) => {
  console.error("Stream closed or error encountered:", err);
  eventSource.close();
};
```

---

## 5. Verification & Testing

Verify that all components are properly wired together by running the complete integration test suite:

```powershell
# Run engine tests, backend tests, and agent test suites
python -m pytest tests/engine/ tests/backend/ tests/test_planner_pipeline.py -v
```
