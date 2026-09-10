# TestSphere-AI: Autonomous Agentic QA & Self-Healing Testing Platform

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Pydantic](https://img.shields.io/badge/Pydantic-v2-e92063.svg)](https://docs.pydantic.dev/)
[![Tests](https://img.shields.io/badge/Tests-475%20Passed-brightgreen.svg)]()
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

## 🦜 LangChain Integration for Test Planner (Day 7)

Day 7 introduces LangChain into the Test Planner pipeline while fully preserving the existing architecture, provider independence, and 100% offline determinism:

```
ApplicationContext
        │
        ▼
┌─────────────────────────────────┐
│   TestPlannerPromptTemplate     │  ──> LangChain ChatPromptTemplate management
│   (System + Human Messages)     │      with modular section partialing
└───────────────┬─────────────────┘
                │ Formatted Messages
                ▼
┌─────────────────────────────────┐
│   LangChainPlanningAdapter      │  ──> Bridges LangChain templates with LLMClientSession;
│                                 │      handles message conversion & generation parameters
└───────────────┬─────────────────┘
                │
                ▼
┌─────────────────────────────────┐
│      LLMClientSession           │  ──> Provider-independent execution (MockLLMProvider)
└───────────────┬─────────────────┘
                │ Raw String / JSON
                ▼
┌─────────────────────────────────┐
│   StructuredOutputProcessor     │  ──> Markdown code-fence stripping, type coercion,
│                                 │      Pydantic schema validation (TestPlan / TestCase)
└───────────────┬─────────────────┘
                │ Validated Pydantic Models
                ▼
┌─────────────────────────────────┐
│    Business-Rule Validation     │  ──> Domain rule enforcement (actions, assertions)
└───────────────┬─────────────────┘
                │
                ▼
┌─────────────────────────────────┐
│   Duplicate Detection & Element │  ──> Signature deduplication & hallucination filtering
│         Ref Validation          │
└───────────────┬─────────────────┘
                │
                ▼
     Final Validated TestPlan
```

### Key Components & Capabilities:
- **`TestPlannerPromptTemplate` (`agents/planner/langchain_prompts.py`)**:
  - Leverages LangChain's `ChatPromptTemplate`, `SystemMessagePromptTemplate`, and `HumanMessagePromptTemplate`.
  - Encapsulates system instructions, controlled action/assertion vocabularies, schema rules, and contextual formatting.
  - Supports custom prompt overrides, serialization helpers, and direct string/message generation.
- **`LangChainPlanningAdapter` (`agents/planner/langchain_adapter.py`)**:
  - Bridges LangChain prompt management with the project's internal `LLMClientSession`.
  - Converts LangChain messages into formatted LLM prompts with appropriate generation parameters (`temperature`, `max_tokens`, `response_format`).
  - Implements fail-safe fallbacks: cleanly returns raw content or structured dicts even on formatting edge cases.
- **`StructuredOutputProcessor` (`agents/planner/structured_output.py`)**:
  - Robust post-processing for LLM outputs: strips markdown code fences (````json ... ````), extracts JSON payloads from mixed text, coerces string step numbers and enum casing.
  - Validates outputs against Pydantic schemas (`TestPlan`, `TestCase`, `TestStep`, `Assertion`) with clear diagnostics and `StructuredOutputError`.
- **`LangChainTestPlanner` (`agents/planner/planner.py`)**:
  - Direct extension of the generation pipeline powered by LangChain orchestration.
  - Supports `generate_tests()`, `generate_test_plan()`, deduplication, and element reference validation.
  - Completely backwards-compatible: existing `LLMTestPlanner` remains untouched as a drop-in alternative.
- **100% Offline & Zero API Keys**:
  - Fully compatible with `MockLLMProvider` and existing mock scenario fixtures.
  - Zero external cloud calls required for local execution and automated testing.
- **95 Comprehensive Tests**:
  - Added `tests/test_day7_langchain_integration.py` testing prompt templates, adapter behavior, structured output parsing/coercion, end-to-end planning, mock scenarios, error handling, and regression parity.
  - Overall test suite expanded from 380 to **475 passing tests**.

---

## 🧠 Historical Memory & Context Management Layer (Day 8)

Day 8 introduces the foundation for historical test execution tracking, failure pattern querying, UI element snapshot evolution, and context comparison, establishing the memory subsystem for self-healing and adaptive test planning:

```
Test Execution / UI Run / Self-Healing Event
                      │
                      ▼
┌───────────────────────────────────────────┐
│              MemoryStore (ABC)            │  ──> Storage-independent memory abstraction
│  (store/query executions, failures, etc.) │      defining contract for all backends
└─────────────────────┬─────────────────────┘
                      │
                      ▼
┌───────────────────────────────────────────┐
│              InMemoryStore                │  ──> High-performance dict-backed store:
│  • Execution history (by test/app/status) │      - Isolated deep copies on store/retrieve
│  • Failure query index                    │      - Pagination (limit & offset)
│  • Element snapshot tracking by page      │      - Element snapshot history & timelines
│  • Healing history & pattern lookups      │      - Selector-based healing rate queries
└─────────────────────┬─────────────────────┘
                      │
                      ▼
┌───────────────────────────────────────────┐
│             ContextComparator             │  ──> UI Context Diff Engine:
│  • compare_contexts(prev, current)        │      - Detects ADDED, REMOVED, MODIFIED
│  • compare_element_snapshots(e1, e2)      │      - Multi-attribute tracking & field diffs
│  • ChangeType & FieldChange detail        │      - Structural tag/selector change detection
└───────────────────────────────────────────┘
```

### Key Components & Capabilities:
- **`MemoryStore` Interface (`agents/memory/memory_interface.py`)**:
  - Storage-independent Abstract Base Class defining contracts for storing/querying test executions, failure histories, element snapshots, and healing attempts.
  - Future-ready for SQLite, PostgreSQL, MongoDB, or vector database backends without changing downstream agent interfaces.
- **`InMemoryStore` (`agents/memory/in_memory_store.py`)**:
  - Complete concrete implementation with in-memory indexes for fast retrieval.
  - Safe mutation handling using deep copying to prevent shared mutable state leaks.
  - Comprehensive query capabilities: filtering by `test_name`, `app_name`, `status`, pagination (`limit`, `offset`), failure filtering, element versioning, and selector-based healing success rates.
- **`ContextComparator` (`agents/memory/context_comparator.py`)**:
  - Deterministic UI element diff engine comparing element snapshots across test runs or page context transitions.
  - Classifies changes as `ADDED`, `REMOVED`, `MODIFIED`, or `UNCHANGED`.
  - Pinpoints specific field-level attribute variations (`tag_name`, `selector`, `attributes`, `text_content`, `is_interactive`) with `FieldChange` records.
- **Pydantic Memory Schemas (`agents/memory/memory_schemas.py`)**:
  - Strictly typed contracts: `TestExecutionRecord`, `FailureInfo`, `ElementRecord`, `HealingRecord`, `FieldChange`, and `ContextComparisonResult`.
  - Schema-level validations: ISO timestamps, positive durations, probability ranges (`0.0 <= success_rate <= 1.0`), and non-empty selector constraints.
- **New Core Enums (`agents/schemas/enums.py`)**:
  - `ExecutionStatus`: `PASSED`, `FAILED`, `ERROR`, `SKIPPED`, `RUNNING`.
  - `ChangeType`: `ADDED`, `REMOVED`, `MODIFIED`, `UNCHANGED`.
- **57 Comprehensive Tests**:
  - Added `tests/test_day8_memory.py` covering model validations, pagination, filtering, snapshot versioning, healing rate tracking, context comparison diffs, and immutability.
  - Overall test suite expanded from 475 to **532 passing tests** (100% offline, 0 failures).

---

## 🔍 Failure Analysis Agent (Day 9)

Day 9 introduces the **Failure Analysis Agent**, diagnosing test execution failures and identifying their root cause across five distinct signals without performing self-healing directly:

```
                  ┌──────────────────────────────────────────────┐
                  │                Failure Context               │
                  │  (test_name, step, selector, error message)  │
                  └──────────────────────┬───────────────────────┘
                                         │
        ┌────────────────────────────────┼───────────────────────────────┐
        ▼                                ▼                               ▼
┌───────────────┐              ┌───────────────────┐           ┌───────────────────┐
│ Memory Store  │              │  Element Context  │           │Structured Evidence│
│  & Execution  │              │(previous snapshot │           │ (console logs,    │
│    History    │              │ vs. current DOM)  │           │ network errors,   │
│  (flakiness,  │              │(tag, attrs, text, │           │  screenshot URL)  │
│  recurrence)  │              │ similarity drift) │           │                   │
└───────┬───────┘              └─────────┬─────────┘           └─────────┬─────────┘
        │                                │                               │
        └────────────────────────────────┼───────────────────────────────┘
                                         ▼
        ┌────────────────────────────────────────────────────────────────┐
        │            RuleBasedFailureAnalyzer / Multi-Signal Engine      │
        │  • Error pattern heuristic matching & category classification │
        │  • Context comparator & DOM attribute drift analysis          │
        │  • Execution history recurrence & flakiness evaluation        │
        │  • Structured evidence correlation (network/console/status)   │
        │  • Self-healing candidate qualification & strategy generation │
        └────────────────────────────────┬───────────────────────────────┘
                                         │
                                         ▼
        ┌────────────────────────────────────────────────────────────────┐
        │                     FailureAnalysisResult                      │
        │  • failure_type & failure_category (SELECTOR_ISSUE, etc.)      │
        │  • root_cause & detailed diagnostic explanation                │
        │  • confidence & confidence_level (HIGH, MEDIUM, LOW)           │
        │  • is_retryable & eligible_for_self_healing                    │
        │  • suggested_strategies (candidate selectors & heuristics)     │
        └────────────────────────────────────────────────────────────────┘
```

### Key Components & Capabilities:
- **`FailureAnalysisAgent` & `RuleBasedFailureAnalyzer` (`agents/analyzer/analyzer.py`)**:
  - Abstract base agent interface (`FailureAnalysisAgent`) defining `analyze_failure()` with full multi-signal context support (`execution_history`, `previous_element_context`, `current_element_context`, `structured_evidence`), along with backward-compatible single-argument `analyze()`.
  - Concrete rule-based heuristic diagnostic engine (`RuleBasedFailureAnalyzer`) operating fully offline with zero mandatory LLM token overhead.
  - Multi-signal diagnosis: error pattern heuristics, historical memory querying, DOM element drift comparison, evidence correlation, and confidence scoring.
- **Strict Self-Healing Boundary**:
  - The analyzer's sole responsibility is **diagnosis**, classifying root causes and qualifying whether a failure is eligible for self-healing (`eligible_for_self_healing = True/False`).
  - It proposes healing strategies (`suggested_strategies`) but explicitly leaves selector mutation and execution to the future Self-Healing Agent (Day 10) and Execution Engine (Member 2).
- **Pydantic Failure Schemas (`agents/analyzer/schemas.py`)**:
  - `FailureContext`: Test name, step index/description, failed selector, error message, stack trace, timestamp, and optional page/app context.
  - `PreviousExecutionSummary`: Total runs, pass/fail counts, failure rate, consecutive failures, and last pass/fail timestamps.
  - `ElementContextSnapshot`: Structured snapshot of element attributes, tag, text, and selector before/after failure.
  - `FailureEvidence`: Screenshots, console logs, network error logs, HTTP response codes, and page title.
  - `FailureAnalysisResult`: Structured diagnosis with `root_cause`, `failure_type`, `failure_category`, calibrated numeric `confidence`, `confidence_level`, `is_retryable`, `eligible_for_self_healing`, `suggested_strategies`, and evidence references.
- **Core Enums & Contracts (`agents/schemas/enums.py`)**:
  - `FailureCategory`: `SELECTOR_ISSUE`, `TIMING_ISSUE`, `APPLICATION_BUG`, `ENVIRONMENT_ISSUE`, `TEST_DATA_ISSUE`, `UNKNOWN`.
  - `ConfidenceLevel`: `HIGH`, `MEDIUM`, `LOW`.
  - `FailureType.SELECTOR_CHANGED`: Added to existing failure types (`ELEMENT_NOT_FOUND`, `TIMEOUT`, `ASSERTION_FAILED`, etc.).
- **Seamless Memory & Context Integration**:
  - Direct integration with Day 8 `MemoryStore` (`InMemoryStore`) and `ContextComparator` to automatically query historical runs and compute DOM element diffs.
- **Full Backward Compatibility**:
  - `TestFailure = FailureContext` and `FailureAnalysis = FailureAnalysisResult` aliases preserve backwards compatibility with all earlier modules and tests.
- **61 Comprehensive Unit Tests (`tests/test_day9_failure_analyzer.py`)**:
  - Thorough testing covering selector drift, timeouts, assertions, network crashes, multi-signal evidence, confidence level calculation, memory store integration, and immutability.
  - Overall test suite expanded from 532 to **593 passing tests** (100% offline, 0 failures).

---

## 📂 Project Structure (`agents/`)

```
.
├── agents/
│   ├── analyzer/              # Failure Analysis Agent & Schemas (Day 9)
│   │   ├── analyzer.py        # FailureAnalysisAgent ABC + RuleBasedFailureAnalyzer
│   │   └── schemas.py         # FailureContext, FailureAnalysisResult, FailureEvidence, etc.
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
│   ├── memory/                # Historical Memory & Context Management (Day 8)
│   │   ├── context_comparator.py # Element diff engine (added, removed, modified elements)
│   │   ├── healing_history.py # Abstract HealingMemory interface (legacy compatibility)
│   │   ├── in_memory_store.py # InMemoryStore with filtering, snapshots & query helpers
│   │   ├── memory_interface.py# Storage-independent MemoryStore ABC
│   │   └── memory_schemas.py  # TestExecutionRecord, FailureInfo, ElementRecord, HealingRecord
│   ├── orchestration/         # Pipeline Controller
│   │   └── agent_controller.py# Abstract AgentController
│   ├── planner/               # Test Planner Agent & Generation Pipeline (Day 4 + Day 5 + Day 7)
│   │   ├── langchain_adapter.py # LangChain adapter bridging templates to LLMClientSession
│   │   ├── langchain_prompts.py # LangChain ChatPromptTemplate management for test planning
│   │   ├── mock_scenarios.py  # 9 mock LLM response fixtures for deterministic testing
│   │   ├── planner.py         # Abstract TestPlannerAgent + LLMTestPlanner + LangChainTestPlanner
│   │   ├── prompts.py         # Prompt architecture & reusable prompt templates
│   │   ├── schemas.py         # ElementContext, PageContext, ApplicationContext, TestCase, TestStep, Assertion, TestPlan
│   │   ├── structured_output.py # JSON extraction, coercion & schema validation for LLM outputs
│   │   └── validation.py      # Business-rule validation + element refs + duplicate detection
│   └── schemas/               # Shared Enums & Data Contracts
│       ├── contracts.py       # Re-exported single source of truth (including memory schemas)
│       └── enums.py           # FailureType, HealingStatus, TestPriority, TestCategory, TestAction, AssertionType, ExecutionStatus, ChangeType, FailureCategory, ConfidenceLevel
├── docs/
│   └── member1-architecture.md# Comprehensive architectural specification (v0.5.0)
├── tests/
│   ├── test_config.py             # Config loading & immutability tests
│   ├── test_day6_response_validation.py # Day 6 response validation & hardening (41 tests)
│   ├── test_day7_langchain_integration.py # Day 7 LangChain integration tests (95 tests)
│   ├── test_day8_memory.py        # Day 8 historical memory & context comparator tests (57 tests)
│   ├── test_day9_failure_analyzer.py # Day 9 failure analyzer agent & diagnostic tests (61 tests)
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
- [x] **Day 5**: Full generation pipeline (`LLMTestPlanner.generate_tests()` / `generate_test_plan()`), duplicate test case detection, and hallucinated element reference validation.
- [x] **Day 6**: LLM response validation hardening & mock scenario alignment: fixed normalization logic, added explicit `LLMParsingError` and `LLMSchemaValidationError`, case-insensitive mock registry matching, default planner scenario registration helper, and 41 regression tests (380 tests total).
- [x] **Day 7**: LangChain integration for Test Planner: prompt template management (`ChatPromptTemplate`), structured output handling with field coercion & validation (`StructuredOutputProcessor`), adapter bridging LangChain and `LLMClientSession` (`LangChainPlanningAdapter`), backwards-compatible `LangChainTestPlanner`, and 95 tests (475 tests total).
- [x] **Day 8**: Historical Memory and Context Management Layer: storage-independent `MemoryStore` interface, `InMemoryStore` implementation with filtering/pagination/element snapshots/healing lookups, Pydantic memory schemas (`TestExecutionRecord`, `FailureInfo`, `ElementRecord`, `HealingRecord`, `FieldChange`, `ContextComparisonResult`), `ContextComparator` element diff engine, and 57 tests (532 tests total).
- [x] **Day 9**: Failure Analyzer Agent: multi-signal root cause diagnosis, Pydantic failure schemas (`FailureContext`, `FailureAnalysisResult`, `FailureEvidence`, `ElementContextSnapshot`), `FailureCategory` & `ConfidenceLevel` enums, self-healing eligibility evaluation, `MemoryStore` historical context correlation, backwards-compatible schemas/agent signatures, and 61 tests (593 tests total).
- [ ] **Day 10–12**: Self-Healing Agent & semantic DOM selector ranking.
- [ ] **Day 13–15**: Persistent Healing Memory & Vector Storage integration.
- [ ] **Day 16–18**: Full pipeline orchestration & integration with Member 2 & 3.



