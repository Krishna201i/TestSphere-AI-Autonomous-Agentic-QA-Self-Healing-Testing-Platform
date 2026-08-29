# TestSphere-AI — Member 1: AI Intelligence Layer Architecture

> **Version:** 0.1.0 (Day 1 Foundation)
> **Author:** Member 1
> **Date:** 2026-08-29

---

## 1. Team Responsibilities

### Member 1 — AI Agent & Intelligence Layer

- LLM integration and abstraction
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

## 7. Module Structure

```
agents/
├── __init__.py
├── llm/
│   ├── __init__.py
│   ├── client.py          ← Abstract LLM client interface
│   └── config.py          ← LLM configuration from env vars
├── planner/
│   ├── __init__.py
│   ├── planner.py         ← Abstract Test Planner Agent
│   └── schemas.py         ← ApplicationContext, TestCase, TestStep, Assertion
├── analyzer/
│   ├── __init__.py
│   ├── analyzer.py        ← Abstract Failure Analyzer Agent
│   └── schemas.py         ← TestFailure, FailureAnalysis
├── healer/
│   ├── __init__.py
│   ├── healer.py          ← Abstract Self-Healing Agent
│   └── schemas.py         ← HealingCandidate, HealingResult
├── memory/
│   ├── __init__.py
│   └── healing_history.py ← Abstract Healing Memory store
├── orchestration/
│   ├── __init__.py
│   └── agent_controller.py ← Abstract Agent Controller
└── schemas/
    ├── __init__.py
    ├── enums.py           ← FailureType, HealingStatus, TestPriority, TestCategory
    └── contracts.py       ← Re-exports all contracts from one import path
```

---

## 8. Future Implementation Phases

| Phase   | Focus                                           | Dependencies         |
| ------- | ----------------------------------------------- | -------------------- |
| Day 1   | Architecture, interfaces, schemas, contracts     | None                 |
| Day 2–3 | Concrete LLM client (OpenAI/Anthropic)          | LLM API key          |
| Day 4–5 | Test Planner Agent implementation                | LLM client           |
| Day 6–8 | Failure Analyzer Agent implementation            | LLM client           |
| Day 9–12 | Self-Healing Agent + selector ranking           | Analyzer, DOM access  |
| Day 13–15 | Healing Memory (persistent store)              | Database (Member 3)   |
| Day 16–18 | Agent Controller orchestration                 | All agents            |
| Day 19–22 | Integration with Member 2 execution engine     | Member 2 APIs         |
| Day 23–25 | Integration with Member 3 backend/dashboard    | Member 3 APIs         |
| Day 26–28 | Confidence calibration and evaluation          | Historical data       |
| Day 29–30 | End-to-end testing and hardening               | All components        |

---

## 9. Inter-Member Integration Points

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

*This document will be updated as the architecture evolves on future development days.*
