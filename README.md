# TestSphere-AI: Autonomous Agentic QA & Self-Healing Testing Platform

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Pydantic](https://img.shields.io/badge/Pydantic-v2-e92063.svg)](https://docs.pydantic.dev/)
[![Tests](https://img.shields.io/badge/Tests-380%20Passed-brightgreen.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**TestSphere-AI** is an intelligent, multi-agent autonomous testing platform designed to plan, generate, execute, analyze, and self-heal end-to-end web application tests.

---

## 👥 Team Responsibilities & Division of Labor

- **Member 1 (AI Agent & Intelligence Layer - `vinamra-branch`)**:
  - LLM integration & provider-independent client abstraction (`LLMClientSession`, `LLMClient`)
  - Test Planner Agent (test generation, controlled actions/assertions, prioritization, validation)
  - Failure Analyzer Agent (classification & root cause analysis)
  - Self-Healing Agent (selector ranking & confidence scoring)
  - Healing Memory & historical learning
  - Agent Orchestration & pipeline controller
- **Member 2 (Execution Engine)**:
  - Playwright browser automation
  - DOM snapshot & screenshot extraction
  - Test execution engine
  - Selector healing execution & validation
- **Member 3 (Platform & Infrastructure)**:
  - Backend API & database
  - Frontend dashboard & reporting
  - Application-level workflow orchestration

---

## 🏛️ AI Agent Pipeline & Architecture

```
ApplicationContext
        │
        ▼
┌───────────────────────────┐
│     Test Planner Agent    │  ──> Generates structured TestCase & TestPlan models
└─────────────┬─────────────┘
              │
              ▼
         TestPlan / list[TestCase]
              │
              ▼
┌───────────────────────────┐
│ Member 2 Execution Engine │  ──> Executes tests with Playwright
└─────────────┬─────────────┘
              │
        ┌─────┴─────┐
        │           │
      PASS        FAIL
        │           │
        ▼           ▼
     Report    TestFailure
                    │
                    ▼
       ┌───────────────────────────┐
       │   Failure Analysis Agent  │  ──> Categorizes failure & root cause
       └────────────┬──────────────┘
                    │
                    ▼
             FailureAnalysis
          (healable? confidence?)
                    │
              ┌─────┴─────┐
              │           │
         [healable]  [not healable]
              │           │
              ▼           ▼
    ┌──────────────────┐ Report
    │Self-Healing Agent│ ──> Generates candidate selectors with DOM evidence
    └─────────┬────────┘
              │
              ▼
       HealingCandidate
              │
              ▼
    ┌──────────────────┐
    │Member 2 Validate │ ──> Tests proposed selector in browser
    └─────────┬────────┘
              │
        ┌─────┴─────┐
        │           │
     SUCCESS     FAILURE
        │           │
        ▼           ▼
    ┌───────────┐ Report
    │  Memory   │ ──> Records outcome in HealingMemory
    └───────────┘
```

---

## 🧠 Test Planner Agent — Generation Pipeline (Day 4 + Day 5)

The **Test Planner Agent** converts structured application information into meaningful, executable test plans via a complete end-to-end generation pipeline.

```
ApplicationContext
        │
        ▼
┌───────────────────────────┐
│    Input Validation       │  ──> Validates app name, URL, pages, elements
└─────────────┬─────────────┘
              │
              ▼
┌───────────────────────────┐
│       LLMTestPlanner      │  ──> Prompt construction + LLM invocation
│  • System Prompt          │
│  • Action/Assertion Vocab │
│  • Context Serialization  │
└─────────────┬─────────────┘
              │ (generate_json)
              ▼
┌───────────────────────────┐
│     LLMClientSession      │  ──> Provider-independent client (retry + validation)
└─────────────┬─────────────┘
              │
              ▼
┌───────────────────────────┐
│      MockLLMProvider      │  ──> Deterministic mock (9 scenarios)
└─────────────┬─────────────┘
              │
              ▼
        Raw JSON Response
              │
              ▼
┌───────────────────────────┐
│    Response Parsing       │  ──> JSON → TestPlan via Pydantic model_validate
└─────────────┬─────────────┘
              │
              ▼
┌───────────────────────────┐
│  Business-Rule Validation │  ──> Action requirements, assertion contracts
└─────────────┬─────────────┘
              │
              ▼
┌───────────────────────────┐
│   Duplicate Detection     │  ──> Signature-based deduplication
└─────────────┬─────────────┘
              │
              ▼
┌───────────────────────────┐
│ Element Ref Validation    │  ──> Rejects hallucinated element targets
└─────────────┬─────────────┘
              │
              ▼
   Valid TestPlan / Cases
```

### Key Capabilities (Day 4 + Day 5):
- **Rich Context Schemas**: `ElementContext` (tags, attributes, classes, accessibility roles, selectors, visibility/interactability), `PageContext` (title, elements, forms, navigation elements), and `ApplicationContext`.
- **Controlled Action Vocabulary (`TestAction`)**: 8 strictly supported browser actions (`navigate`, `click`, `fill`, `select`, `check`, `uncheck`, `press`, `wait`) with mapped parameter requirements (target/value).
- **Controlled Assertion Vocabulary (`AssertionType`)**: 7 verifiable assertion types (`element_visible`, `element_not_visible`, `element_contains_text`, `element_has_text`, `url_contains`, `url_equals`, `value_equals`).
- **Standardized Categories & Priorities**: 7 test categories (`functional`, `negative`, `boundary`, `smoke`, `regression`, `edge_case`, `accessibility`) and 4 priorities (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`).
- **Two-Layer Validation**: Pydantic structural validation + domain business rules in `agents/planner/validation.py` (checks required targets/values per action, non-duplicate step numbering, duplicate test IDs, and assertion contracts).
- **Prompt Architecture**: Modular, reusable prompt building blocks in `agents/planner/prompts.py` (system instructions, vocabulary tables, category/priority definitions, JSON output constraints).
- **Deterministic Mock Scenarios**: 9 mock LLM response fixtures in `agents/planner/mock_scenarios.py` covering valid plans, empty plans, malformed JSON, unsupported actions, missing fields, invalid categories/priorities, hallucinated elements, and duplicate test cases.
- **Full Generation Pipeline (Day 5)**: `LLMTestPlanner.generate_tests()` and `generate_test_plan()` — complete flow from ApplicationContext through prompt construction, LLM invocation, response parsing, validation, duplicate detection, and element reference checking.
- **Hallucinated Element Detection**: `validate_element_references()` checks step targets against selectors derivable from the ApplicationContext (IDs, names, tags, data-testid, text, placeholders).
- **Duplicate Test Case Detection**: `detect_duplicate_test_cases()` uses signature-based matching (name + category + action:target sequence) to remove identical or near-identical test cases.
- **Provider-Independent**: Swapping `MockLLMProvider` for a real `LocalLLMProvider` requires zero changes to the planner code.

---

## 🤖 LLM Client Architecture (Day 2 & Day 3 Foundation)

All AI agents interact with models strictly through the provider-independent `LLMClientSession` and `LLMClient` interfaces:

```
                ┌───────────────────┐
                │     AI AGENTS     │
                │ Planner / Healer  │
                └─────────┬─────────┘
                          │ (generate, generate_json, complete)
                          ▼
                ┌───────────────────┐
                │  LLMClientSession │  ──> Request validation, normalization,
                └─────────┬─────────┘      retry logic, timeout & error translation
                          │
                          ▼
                ┌───────────────────┐
                │     LLMClient     │  ──> Abstract provider interface
                └─────────┬─────────┘
                          │
                  ┌───────┴────────┐
                  ▼                ▼
          MockLLMProvider   Future Providers (Local / API)
                  │                │
             Deterministic     Ollama / Cloud Models
             Mock Registry
```

### Key LLM Client Features:
- **Provider Independence**: Seamless switching between `mock`, `local` (future), and `api` (future) via `LLM_PROVIDER`.
- **Request Validation**: Enforces prompt presence, valid sampling parameters (`temperature` 0.0–2.0, `max_tokens` > 0), and supported response formats.
- **Response Normalization**: Uniform standard `LLMResponse` models with populated provider/model metadata and token usage stats.
- **Resilient Retry Logic**: Automatically retries transient errors (`LLMProviderError`, `LLMTimeoutError`, `LLMConnectionError`, `LLMRateLimitError`) up to configured `LLM_MAX_RETRIES`.
- **Error Hierarchy**: 10 granular exception types rooted in `LLMError` with `is_retryable` property (including `LLMParsingError` and `LLMSchemaValidationError`).
- **Mock Response Registry**: Flexible offline mocking by prompt pattern matching, custom error injection, and transient failure sequence testing.
- **Zero Secrets Logged / Committed**: Strict safeguards ensure credentials and raw API keys are never logged or committed.

---

## 🛡️ LLM Response Validation & Hardening (Day 6)

Day 6 focused on hardening the LLM response processing pipeline and resolving mock scenario registry matching issues:

- **Response Normalization Bug Fix**: Fixed logic bug in `LLMClientSession._normalize_response()` where `not content and not tool_calls` previously allowed empty text responses through when tool calls were absent.
- **Strict Content Guardrails**: Enforced explicit type validation ensuring `content` is a non-empty string when no tool calls are present (rejecting `None`, empty string, whitespace-only, numbers, dicts, or lists).
- **Error Finish Reason Handling**: Enforced that responses with `finish_reason="error"` are rejected immediately with `LLMResponseError`.
- **Granular Exception Hierarchy**: Added `LLMParsingError` (for malformed/unparseable JSON) and `LLMSchemaValidationError` (for Pydantic model validation failures), both cleanly inheriting from `LLMResponseError`.
- **ResponseParser Modernization**: `ResponseParser.parse_json()` now raises `LLMParsingError` with raw content diagnostics, and `ResponseParser.parse_model()` now raises `LLMSchemaValidationError` with target schema metadata.
- **Case-Insensitive Mock Matching**: `MockLLMProvider` pattern matching now normalizes prompts and registry keys via `.lower()` comparison so matching is resilient to casing discrepancies.
- **Planner Mock Scenario Alignment**: Aligned the default planner mock scenario key (`"Generate up to"`) with the real prompt prefix generated by `LLMTestPlanner.generate_tests()`, and added `register_default_planner_scenario(client)` for clean test setup.
- **41 New Regression Tests**: Added `tests/test_day6_response_validation.py` covering all edge cases, bringing the test suite to 380 passing tests.

---

## 📂 Project Structure (`agents/`)

```
.
├── agents/
│   ├── analyzer/              # Failure Analysis Agent & Schemas
│   │   ├── analyzer.py        # Abstract FailureAnalyzerAgent
│   │   └── schemas.py         # TestFailure, FailureAnalysis
│   ├── healer/                # Self-Healing Agent & Schemas
│   │   ├── healer.py          # Abstract SelfHealingAgent
│   │   └── schemas.py         # HealingCandidate, HealingResult
│   ├── llm/                   # LLM Client Abstraction & Infrastructure
│   │   ├── client.py          # Abstract LLMClient + Concrete LLMClientSession
│   │   ├── config.py          # LLMConfig (env-based configuration, defaults to 'mock')
│   │   ├── exceptions.py      # LLM exception hierarchy (10 types + is_retryable)
│   │   ├── factory.py         # Provider factory (get_llm_provider, create_llm_client)
│   │   ├── parser.py          # ResponseParser (text, JSON, Pydantic model validation)
│   │   ├── schemas.py         # LLMRequest, LLMResponse, LLMUsage models + validators
│   │   └── providers/
│   │       └── mock.py        # MockLLMProvider with simulations & response registry
│   ├── memory/                # Healing Memory Store
│   │   └── healing_history.py # Abstract HealingMemory interface
│   ├── orchestration/         # Pipeline Controller
│   │   └── agent_controller.py# Abstract AgentController
│   ├── planner/               # Test Planner Agent & Generation Pipeline (Day 4 + Day 5)
│   │   ├── mock_scenarios.py  # 9 mock LLM response fixtures for deterministic testing
│   │   ├── planner.py         # Abstract TestPlannerAgent + LLMTestPlanner with full pipeline
│   │   ├── prompts.py         # Prompt architecture & reusable prompt templates
│   │   ├── schemas.py         # ElementContext, PageContext, ApplicationContext, TestCase, TestStep, Assertion, TestPlan
│   │   └── validation.py      # Business-rule validation + element refs + duplicate detection
│   └── schemas/               # Shared Enums & Data Contracts
│       ├── contracts.py       # Re-exported single source of truth
│       └── enums.py           # FailureType, HealingStatus, TestPriority, TestCategory, TestAction, AssertionType
├── docs/
│   └── member1-architecture.md# Comprehensive architectural specification (v0.5.0)
├── tests/
│   ├── test_config.py             # Config loading & immutability tests
│   ├── test_day6_response_validation.py # Day 6 response validation & hardening (41 tests)
│   ├── test_fixtures.py           # Reusable test factories & sample data (Day 5)
│   ├── test_imports.py            # Module import validation tests
│   ├── test_llm_client.py         # Day 2 LLM foundation & mock provider tests
│   ├── test_llm_client_session.py # Day 3 LLM client session & integration tests
│   ├── test_planner_agent.py      # LLMTestPlanner agent & prompt tests
│   ├── test_planner_pipeline.py   # Day 5 full generation pipeline tests (50 tests)
│   ├── test_planner_schemas.py    # Day 4 ElementContext, PageContext, TestPlan schema tests
│   ├── test_planner_validation.py # Day 4 action & assertion business rule validation tests
│   └── test_schemas.py            # Pydantic schema validation tests
├── .env.example               # Template for environment variables
├── .gitignore                 # Secret & artifact protection
└── pyproject.toml             # Python packaging & dependency configuration
```

---

## 🛡️ Core Healing Principles

1. **DOM Evidence Required**: The AI must never invent selectors without evidence from the actual DOM.
2. **No Self-Declaration**: The AI must never declare healing successful by itself.
3. **Execution Engine Validates**: Member 2's execution engine validates every proposed candidate.
4. **Safe Fallbacks**: The AI can return `NO_SAFE_HEALING_FOUND` when confidence is insufficient.
5. **Confidence Scoring**: Every analysis and healing candidate includes a calibrated confidence score (`0.0` to `1.0`).
6. **Conservative Auto-Healing**: Low-confidence suggestions will not automatically modify test suites.
7. **Strictly Typed & Validated**: All inter-agent data flow is strictly typed with Pydantic v2 schemas.
8. **Zero Secret Leaks**: API keys are managed purely through environment variables and never checked into Git.

---

## 🚀 Getting Started

### 1. Installation

```bash
# Clone the repository and checkout the branch
git clone https://github.com/Krishna201i/TestSphere-AI-Autonomous-Agentic-QA-Self-Healing-Testing-Platform.git
cd TestSphere-AI-Autonomous-Agentic-QA-Self-Healing-Testing-Platform
git checkout vinamra-branch

# Install in editable mode with development dependencies
pip install -e ".[dev]"
```

### 2. Environment Setup

```bash
cp .env.example .env
# Edit .env if needed (defaults to fully offline LLM_PROVIDER=mock)
```

### 3. Run Tests (100% Offline)

```bash
python3 -m pytest tests/ -v
```

---

## 🗺️ Roadmap

- [x] **Day 1**: Architecture design, Pydantic contracts, agent interfaces, configuration setup, and documentation.
- [x] **Day 2**: Provider-independent LLM abstraction foundation, `MockLLMProvider`, configuration, exception hierarchy, and response parsing.
- [x] **Day 3**: Reusable `LLMClientSession` layer with request validation, response normalization, retry mechanism, timeout handling, error translation, and mock response registry.
- [x] **Day 4**: Test Planner Agent foundation: `ElementContext`, `PageContext`, `TestPlan`, controlled action/assertion vocabularies, two-layer validation, prompt architecture, and mock test scenarios.
- [x] **Day 6**: LLM response validation hardening & mock scenario alignment: fixed normalization logic, added explicit `LLMParsingError` and `LLMSchemaValidationError`, case-insensitive mock registry matching, default planner scenario registration helper, and 41 regression tests (380 tests total).
- [ ] **Day 7–8**: Failure Analyzer Agent & root cause classification.
- [ ] **Day 9–12**: Self-Healing Agent & semantic DOM selector ranking.
- [ ] **Day 13–15**: Persistent Healing Memory store.
- [ ] **Day 16–18**: Full pipeline orchestration & integration with Member 2 & 3.
