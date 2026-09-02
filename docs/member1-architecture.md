# TestSphere-AI — Member 1: AI Intelligence Layer Architecture

> **Version:** 0.4.0 (Day 4 — Test Planner Agent Foundation)
> **Author:** Member 1
> **Date:** 2026-09-02

---

## 1. Team Responsibilities

### Member 1 — AI Agent & Intelligence Layer

- LLM integration and provider-independent abstraction
- AI agent interfaces and orchestration
- Test generation intelligence (Test Planner Agent)
- Failure analysis and root-cause analysis (Failure Analyzer Agent)
- Self-healing intelligence (Self-Healing Agent)
- Selector candidate reasoning, ranking, and confidence scoring
- Healing memory
- AI evaluation and output validation

### Member 2 — Execution Engine

- Playwright / browser automation
- Browser interaction and DOM extraction
- Test execution engine
- Screenshot capture
- Executing proposed healed selectors
- Validating whether healing actually works

### Member 3 — Platform Layer

- Backend API
- Database
- Frontend dashboard
- Reports and analytics
- Application-level orchestration

---

## 2. AI Architecture Overview

```
ApplicationContext
        │
        ▼
┌──────────────────────┐
│  Test Planner Agent  │  ← Generates test cases from app context
└──────────┬───────────┘
           │
           ▼
    list[TestCase]
           │
           ▼
┌──────────────────────┐
│  Member 2: Execution │  ← Runs tests via Playwright
└──────────┬───────────┘
           │
      ┌────┴────┐
      │         │
    PASS      FAIL
      │         │
      ▼         ▼
   Report   ┌──────────────────────────┐
            │  Failure Analyzer Agent  │  ← Classifies failure, finds root cause
            └──────────┬───────────────┘
                       │
                       ▼
              FailureAnalysis
            (healable? confidence?)
                       │
                 ┌─────┴─────┐
                 │           │
            healable    not healable
                 │           │
                 ▼           ▼
   ┌─────────────────────┐  Report
   │  Self-Healing Agent │  ← Proposes selector fix from DOM evidence
   └──────────┬──────────┘
              │
              ▼
      HealingCandidate
    (new_selector, confidence)
              │
              ▼
   ┌─────────────────────┐
   │  Member 2: Validate │  ← Tries the healed selector
   └──────────┬──────────┘
              │
        ┌─────┴─────┐
        │           │
     success     failure
        │           │
        ▼           ▼
   ┌──────────┐  Report
   │  Memory  │  ← Records outcome for future learning
   └──────────┘
```

---

## 3. Agent Responsibilities

| Agent               | Input                        | Output              | Purpose                                    |
| ------------------- | ---------------------------- | -------------------- | ------------------------------------------ |
| Test Planner        | `ApplicationContext`         | `list[TestCase]`     | Generate meaningful, executable test cases  |
| Failure Analyzer    | `TestFailure`                | `FailureAnalysis`    | Classify failure, determine root cause      |
| Self-Healing Agent  | `TestFailure` + DOM snapshot | `HealingCandidate`   | Propose replacement selector from DOM       |
| Agent Controller    | (coordinates all above)      | (varies)             | Orchestrate the full AI pipeline            |

---

## 4. Data Contracts

### 4.1 Planner Contracts

**ApplicationContext** — Input to Test Planner

```json
{
    "app_name": "MyApp",
    "app_url": "https://myapp.example.com",
    "description": "E-commerce platform",
    "pages": [
        {"url": "/login", "name": "Login Page", "description": "User authentication"}
    ],
    "technology_stack": ["React", "Node.js"]
}
```

**TestCase** — Output from Test Planner → Input to Member 2

```json
{
    "test_id": "TC001",
    "name": "Valid Login",
    "description": "Verify that a user can log in with valid credentials.",
    "category": "functional",
    "priority": "HIGH",
    "steps": [
        {
            "step_number": 1,
            "action": "navigate",
            "value": "https://example.com/login",
            "description": "Go to login page"
        },
        {
            "step_number": 2,
            "action": "type",
            "selector": "#username",
            "value": "testuser",
            "description": "Enter username"
        },
        {
            "step_number": 3,
            "action": "click",
            "selector": "#login-button",
            "description": "Click login"
        }
    ],
    "assertions": [
        {
            "type": "url_contains",
            "expected": "/dashboard",
            "description": "Should redirect to dashboard"
        }
    ]
}
```

### 4.2 Failure Contract (from Member 2)

```json
{
    "test_id": "TC001",
    "failed_step": 3,
    "action": "click",
    "selector": "#login-button",
    "error": "Element not found",
    "url": "/login",
    "dom_snapshot": "<html>...</html>",
    "screenshot_path": "/path/to/screenshot.png",
    "expected": "Element should be clickable",
    "actual": "Element not found in DOM"
}
```

### 4.3 Failure Analysis Contract (from Member 1)

```json
{
    "failure_type": "ELEMENT_NOT_FOUND",
    "root_cause": "The original selector no longer identifies the intended element.",
    "healable": true,
    "confidence": 0.94,
    "reasoning": "The selector #login-button is not present in the DOM..."
}
```

### 4.4 Healing Contract (from Member 1 → validated by Member 2)

```json
{
    "test_id": "TC001",
    "failed_step": 3,
    "healing_attempted": true,
    "old_selector": "#login-button",
    "new_selector": "#signin-btn",
    "confidence": 0.94,
    "reason": "The candidate has matching semantic purpose and similar DOM context.",
    "requires_validation": true,
    "status": "PROPOSED",
    "alternative_selectors": ["button[data-testid='login']", ".btn-primary"]
}
```

### 4.5 Healing Result (from Member 2)

```json
{
    "test_id": "TC001",
    "failed_step": 3,
    "old_selector": "#login-button",
    "new_selector": "#signin-btn",
    "status": "VALIDATED_SUCCESS",
    "confidence": 0.94,
    "validated_by": "execution_engine",
    "validation_error": null
}
```

---

## 5. Failure Types

| Failure Type               | Description                                         | Typically Healable? |
| -------------------------- | --------------------------------------------------- | ------------------- |
| `ELEMENT_NOT_FOUND`        | Selector doesn't match any element in the DOM       | Yes                 |
| `ELEMENT_NOT_INTERACTABLE` | Element exists but cannot be interacted with         | Sometimes           |
| `TIMEOUT`                  | Operation timed out waiting for element/condition    | Sometimes           |
| `ASSERTION_FAILURE`        | Element found but assertion on value/state failed    | No                  |
| `NAVIGATION_FAILURE`       | Page navigation failed (404, redirect loop, etc.)    | No                  |
| `NETWORK_ERROR`            | Network request failure                             | No                  |
| `APPLICATION_ERROR`        | Application threw an error (500, unhandled exception)| No                  |
| `UNKNOWN`                  | Failure doesn't match known categories               | No                  |

---

## 6. Healing Principles

These rules govern all self-healing behavior in the system:

1. **DOM Evidence Required** — The AI must never invent selectors without evidence from the actual DOM.
2. **No Self-Declaration** — The AI must never declare healing successful by itself.
3. **Execution Engine Validates** — The execution engine (Member 2) must validate every healing candidate.
4. **Safe Fallback** — The AI must be allowed to return `NO_SAFE_HEALING_FOUND`.
5. **Confidence Scoring** — Every healing decision must contain a confidence score (0.0–1.0).
6. **Conservative Auto-Healing** — Low-confidence healing should not automatically modify a test.
7. **Structured Outputs** — AI outputs must be structured (Pydantic models) and validated.
8. **No Committed Secrets** — API keys must never be committed to Git.

---

## 7. Module Structure (`agents/`)

```
agents/
├── __init__.py
├── llm/
│   ├── __init__.py            ← Exports LLMClient, LLMClientSession, schemas, factory, parser, exceptions
│   ├── client.py              ← Abstract LLMClient interface + LLMClientSession (Day 3)
│   ├── config.py              ← LLM configuration (provider-aware, defaults to 'mock')
│   ├── exceptions.py          ← Custom LLM exception hierarchy (8 types + is_retryable)
│   ├── factory.py             ← get_llm_provider() + create_llm_client() factory functions
│   ├── parser.py              ← ResponseParser (text, JSON, Pydantic model parsing)
│   ├── providers/
│   │   ├── __init__.py        ← Exports MockLLMProvider
│   │   └── mock.py            ← MockLLMProvider (deterministic, failure sims, response registry)
│   └── schemas.py             ← LLMRequest, LLMResponse, LLMUsage (with validators)
├── planner/
│   ├── __init__.py
│   ├── planner.py             ← Abstract TestPlannerAgent + concrete LLMTestPlanner (Day 4)
│   ├── schemas.py             ← ApplicationContext, ElementContext, PageContext, TestCase, TestStep, Assertion, TestPlan
│   ├── validation.py          ← Business-rule validation (action requirements, step ordering, etc.) (Day 4)
│   ├── prompts.py             ← Prompt architecture & templates (Day 4)
│   └── mock_scenarios.py      ← Mock LLM response fixtures for testing (Day 4)
├── analyzer/
│   ├── __init__.py
│   ├── analyzer.py            ← Abstract Failure Analyzer Agent
│   └── schemas.py             ← TestFailure, FailureAnalysis
├── healer/
│   ├── __init__.py
│   ├── healer.py              ← Abstract Self-Healing Agent
│   └── schemas.py             ← HealingCandidate, HealingResult
├── memory/
│   ├── __init__.py
│   └── healing_history.py     ← Abstract Healing Memory store
├── orchestration/
│   ├── __init__.py
│   └── agent_controller.py    ← Abstract Agent Controller
└── schemas/
    ├── __init__.py
    ├── enums.py               ← FailureType, HealingStatus, TestPriority, TestCategory, TestAction, AssertionType (Day 4)
    └── contracts.py           ← Re-exports all contracts from one import path
```

---

## 8. LLM Client Architecture (Day 3)

### 8.1 Layer Responsibilities

The LLM layer uses a three-tier architecture with clear separation of concerns:

```
                 ┌───────────────────┐
                 │   FUTURE AGENTS   │
                 │                   │
                 │ Planner           │
                 │ Analyzer          │
                 │ Healer            │
                 └─────────┬─────────┘
                           ↓
                 ┌───────────────────┐
                 │  LLMClientSession │  ← Day 3: Agent-facing interface
                 │  ─────────────────│
                 │  • Request validation
                 │  • Response normalization
                 │  • Retry logic
                 │  • Timeout handling
                 │  • Error translation
                 │  • Safe logging
                 └─────────┬─────────┘
                           ↓
                 ┌───────────────────┐
                 │     LLMClient     │  ← Abstract provider interface
                 │     (ABC)         │
                 └─────────┬─────────┘
                           ↓
                   ┌───────┴────────┐
                   ↓                ↓
           MockLLMProvider   Future Providers
                   ↓                ↓
              Mock Data        Local/API Model
```

| Layer              | Class                | Responsibility                                          |
| ------------------ | -------------------- | ------------------------------------------------------- |
| **Agent-facing**   | `LLMClientSession`   | Clean, stable interface for agents. Handles validation, retry, normalization, error translation. |
| **Provider ABC**   | `LLMClient`          | Abstract base class defining the `generate()` contract.  |
| **Concrete**       | `MockLLMProvider`    | Provider-specific communication. Deterministic mock for testing. |

### 8.2 Request Flow

```
Agent builds LLMRequest
        ↓
LLMClientSession.generate(request)
        ↓
    ┌── Request Validation ──┐
    │ • Non-empty prompt     │
    │ • Valid temperature     │
    │ • Valid max_tokens      │
    │ • Valid response_format │
    └────────┬───────────────┘
             ↓
    ┌── Provider Delegation ─┐
    │   with retry logic     │──→ (up to max_retries on transient errors)
    └────────┬───────────────┘
             ↓
    ┌── Response Normalization ─┐
    │ • Ensure provider field   │
    │ • Ensure model field      │
    │ • Check non-empty content │
    └────────┬──────────────────┘
             ↓
    ┌── Error Translation ──┐
    │ • Wrap raw exceptions  │
    │ • Project-level errors │
    └────────┬───────────────┘
             ↓
    Standard LLMResponse returned to agent
```

### 8.3 Response Normalization

All provider responses are normalized to the standard `LLMResponse` schema:

- `provider` field is always populated (falls back to config value)
- `model` field is always populated (falls back to config value)
- Empty content is caught and raises `LLMResponseError`
- Token usage statistics are preserved

Agents receive identical response structures regardless of provider.

### 8.4 Error Translation

Provider-specific exceptions are translated to project-level errors:

| Error Type                    | Retryable? | When Raised                                |
| ----------------------------- | ---------- | ------------------------------------------ |
| `LLMConfigurationError`      | No         | Invalid config, unknown provider            |
| `LLMAuthenticationError`     | No         | Invalid credentials (future API providers)  |
| `LLMRequestValidationError`  | No         | Invalid request (empty prompt, bad params)  |
| `LLMResponseError`           | No         | Empty/invalid response, parse failure       |
| `LLMProviderError`           | **Yes**    | Internal provider error (5xx equivalent)    |
| `LLMTimeoutError`            | **Yes**    | Request timeout                             |
| `LLMConnectionError`         | **Yes**    | Cannot reach provider                       |
| `LLMRateLimitError`          | **Yes**    | Rate limited (429 equivalent)               |

Unexpected (non-LLM) exceptions are wrapped in `LLMProviderError` automatically.

### 8.5 Retry Behavior

- Configured via `LLMConfig.max_retries` (default: 2, env: `LLM_MAX_RETRIES`)
- Only **retryable** errors trigger retries (`is_retryable` property)
- Non-retryable errors (config, auth, validation, response) raise immediately
- After all retries exhausted, the last error is raised
- Total attempts = 1 + max_retries

### 8.6 Mock Provider & Response Registry

`MockLLMProvider` supports multiple testing modes:

| Mode                  | Purpose                              | API                                    |
| --------------------- | ------------------------------------ | -------------------------------------- |
| Default               | Deterministic echo-style responses   | `MockLLMProvider(config)`              |
| Simulate              | Fixed failure mode                   | `simulate="error"/"timeout"/…`         |
| Custom responses      | Cycle through predefined strings     | `responses=["A", "B"]`                 |
| Response registry     | Match responses by prompt substring  | `register_response("plan", "…")`       |
| Error registry        | Match errors by prompt substring     | `register_error("crash", exc)`         |
| Failure sequence      | Transient failures then success      | `set_failure_sequence([exc1, exc2])`   |

### 8.7 How to Add a Future Provider

To add a new provider (e.g., `LocalLLMProvider` for Ollama):

1. **Create** `agents/llm/providers/local.py`:
   ```python
   class LocalLLMProvider(LLMClient):
       async def generate(self, request: LLMRequest) -> LLMResponse:
           # Call Ollama API, return LLMResponse
           ...
   ```

2. **Register** in `agents/llm/factory.py`:
   ```python
   if provider == "local":
       from agents.llm.providers.local import LocalLLMProvider
       return LocalLLMProvider(config)
   ```

3. **Configure** via environment:
   ```
   LLM_PROVIDER=local
   LLM_MODEL=llama3.2
   ```

4. **No agent changes required.** All agents use `LLMClientSession` and receive the same `LLMResponse` regardless of provider.

---

## 9. Future Implementation Phases

| Phase   | Focus                                           | Dependencies         | Status   |
| ------- | ----------------------------------------------- | -------------------- | -------- |
| Day 1   | Architecture, interfaces, schemas, contracts     | None                 | ✅ Done  |
| Day 2   | Provider-independent LLM abstraction & Mock     | None (offline)       | ✅ Done  |
| Day 3   | LLMClientSession: validation, retry, normalization | LLM abstraction    | ✅ Done  |
| Day 4   | Test Planner foundation: schemas, validation, prompts | LLM client layer | ✅ Done  |
| Day 5   | Test Planner Agent: full LLM generation logic   | Day 4 foundation     | Planned  |
| Day 6–8 | Failure Analyzer Agent implementation            | LLM client layer     | Planned  |
| Day 9–12 | Self-Healing Agent + selector ranking           | Analyzer, DOM access | Planned  |
| Day 13–15 | Healing Memory (persistent store)              | Database (Member 3)  | Planned  |
| Day 16–18 | Agent Controller orchestration                 | All agents           | Planned  |
| Day 19–22 | Integration with Member 2 execution engine     | Member 2 APIs        | Planned  |
| Day 23–25 | Integration with Member 3 backend/dashboard    | Member 3 APIs        | Planned  |
| Day 26–28 | Confidence calibration and evaluation          | Historical data      | Planned  |
| Day 29–30 | End-to-end testing and hardening               | All components       | Planned  |

---

## 10. Inter-Member Integration Points

### Member 1 → Member 2

- **Output:** `list[TestCase]` (generated test plans for execution)
- **Output:** `HealingCandidate` (proposed selector fixes for validation)
- **Input:** `TestFailure` (failure data with DOM snapshot and screenshot)
- **Input:** `HealingResult` (validation outcome of healing attempt)

### Member 1 → Member 3

- **Output:** `FailureAnalysis` (analysis results for dashboard/reports)
- **Output:** `HealingResult` (healing outcomes for dashboard/reports)
- **Input:** `ApplicationContext` (app info from user via dashboard)
- **Input:** Configuration / trigger signals via backend API

---

## 11. Test Planner Agent — Day 4 Foundation

### 11.1 Responsibility

The Test Planner Agent's **sole responsibility** is to convert structured application information into meaningful, executable test plans.

It does NOT:
- Execute browser actions
- Use Playwright directly
- Modify the application
- Validate healed selectors
- Perform self-healing
- Interact directly with the frontend

Those responsibilities belong to Member 2's execution engine.

### 11.2 Architecture

```
ApplicationContext
        ↓
┌───────────────────┐
│  LLMTestPlanner   │  ← Concrete implementation (Day 4 skeleton)
│  ─────────────────│
│  • Input validation
│  • Prompt building
│  • Output validation
│  • LLMClientSession dependency injection
└─────────┬─────────┘
          ↓
┌───────────────────┐
│  LLMClientSession │  ← Day 3 reusable client
└─────────┬─────────┘
          ↓
┌───────────────────┐
│  MockLLMProvider  │  ← Deterministic mock (no real LLM)
└─────────┬─────────┘
          ↓
   Structured Output
          ↓
┌───────────────────┐
│  Validation Layer │  ← Business-rule validation
└─────────┬─────────┘
          ↓
   Valid Test Cases
```

### 11.3 Enhanced Schemas

| Schema               | Purpose                                              |
| -------------------- | ---------------------------------------------------- |
| `ElementContext`     | Rich DOM element description (tag, id, type, etc.)   |
| `PageContext`        | Page with title, elements, forms, navigation         |
| `ApplicationContext` | Full app description with pages and metadata         |
| `TestStep`           | Atomic action with controlled action vocabulary      |
| `Assertion`          | Verification with controlled assertion types         |
| `TestCase`           | Complete test with steps, assertions, metadata       |
| `TestPlan`           | Wrapper: application name + list of test cases       |

### 11.4 Controlled Action Vocabulary

| Action     | Target Required | Value Required | Description                    |
| ---------- | --------------- | -------------- | ------------------------------ |
| `navigate` | No              | Yes (URL)      | Navigate to a URL              |
| `click`    | Yes             | No             | Click an element               |
| `fill`     | Yes             | Yes (text)     | Type text into an input        |
| `select`   | Yes             | Yes (option)   | Select from a dropdown         |
| `check`    | Yes             | No             | Check a checkbox               |
| `uncheck`  | Yes             | No             | Uncheck a checkbox             |
| `press`    | No              | Yes (key)      | Press a keyboard key           |
| `wait`     | No              | No             | Wait for condition/time        |

### 11.5 Controlled Assertion Types

| Type                    | Target Required | Expected Required | Description                      |
| ----------------------- | --------------- | ----------------- | -------------------------------- |
| `element_visible`       | Yes             | No                | Element is visible               |
| `element_not_visible`   | Yes             | No                | Element is not visible           |
| `element_contains_text` | Yes             | Yes               | Element contains expected text   |
| `element_has_text`      | Yes             | Yes               | Element has exactly expected text|
| `url_contains`          | No              | Yes               | URL contains substring           |
| `url_equals`            | No              | Yes               | URL matches exactly              |
| `value_equals`          | Yes             | Yes               | Input value matches              |

### 11.6 Test Categories

| Category        | Meaning                                                |
| --------------- | ------------------------------------------------------ |
| `functional`    | Tests expected normal user workflows                   |
| `negative`      | Tests invalid or incorrect input/workflows             |
| `boundary`      | Tests minimum, maximum, empty, or edge-case values     |
| `smoke`         | Quick sanity checks that core features work            |
| `regression`    | Tests verifying previously working functionality       |
| `edge_case`     | Tests for unusual or extreme conditions                |
| `accessibility` | Tests verifying accessibility compliance               |

### 11.7 Priority Levels

| Priority   | Meaning                                                       |
| ---------- | ------------------------------------------------------------- |
| `CRITICAL` | System-critical functionality whose failure blocks all usage  |
| `HIGH`     | Critical workflows — login, signup, payment, checkout         |
| `MEDIUM`   | Important but not immediately business-critical               |
| `LOW`      | Minor or low-impact functionality                             |

### 11.8 Validation Rules

Business rules enforced beyond Pydantic schema validation:

- Test ID must be non-empty
- Test name must be non-empty
- Category must be from `TestCategory` enum
- Priority must be from `TestPriority` enum
- Test must contain at least one step
- Step numbers must be sequential and non-duplicate
- Actions must be from `TestAction` enum
- Target required when action needs it (click, fill, select, check, uncheck)
- Value required when action needs it (navigate, fill, select, press)
- Assertion types must be from `AssertionType` enum
- Assertion target required when type needs it
- Assertion expected required when type needs it
- Test plan must have non-empty application name
- No duplicate test IDs within a plan

### 11.9 Prompt Architecture

Modular, reusable prompt components:

| Component                  | Purpose                                              |
| -------------------------- | ---------------------------------------------------- |
| `SYSTEM_PROMPT`            | Role, constraints, rules for the model               |
| `ACTION_VOCABULARY`        | Documents supported actions with requirements        |
| `ASSERTION_VOCABULARY`     | Documents supported assertion types                  |
| `CATEGORY_DEFINITIONS`     | Documents test categories with meanings              |
| `PRIORITY_DEFINITIONS`     | Documents priority levels with meanings              |
| `OUTPUT_SCHEMA_INSTRUCTION`| Expected JSON output format                          |
| `build_test_generation_prompt()` | Assembles context + all components into prompt |

### 11.10 Mock Scenarios

Deterministic test fixtures for the MockLLMProvider:

| Scenario                          | Purpose                                  |
| --------------------------------- | ---------------------------------------- |
| `VALID_TEST_PLAN_RESPONSE`        | Well-formed test plan JSON               |
| `INVALID_MALFORMED_RESPONSE`      | Malformed JSON (parse failure)           |
| `EMPTY_TEST_PLAN_RESPONSE`        | Valid JSON with empty test_cases list    |
| `UNSUPPORTED_ACTION_RESPONSE`     | Test plan with unsupported action        |
| `MISSING_REQUIRED_FIELD_RESPONSE` | Test case missing required fields        |
| `INVALID_CATEGORY_RESPONSE`       | Test case with unsupported category      |
| `INVALID_PRIORITY_RESPONSE`       | Test case with unsupported priority      |

---

*This document will be updated as the architecture evolves on future development days.*
