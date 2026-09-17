# TestSphere-AI: Autonomous Agentic QA & Self-Healing Testing Platform

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Pydantic](https://img.shields.io/badge/Pydantic-v2-e92063.svg)](https://docs.pydantic.dev/)
[![Tests](https://img.shields.io/badge/Tests-882%20Passed-brightgreen.svg)]()
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

## 🩹 Self-Healing Decision & Candidate Generation Foundation (Day 10)

Day 10 establishes the foundation of the **Self-Healing Decision Layer** — the intelligence engine bridging the Failure Analyzer (Day 9) with Member 2's Test Execution Engine. It evaluates failure context, searches both current DOM elements and historical healing records, scores candidates deterministically across multiple weighted dimensions, enforces safety guardrails, and outputs structured `HealingRecommendation` contracts.

```
Failed Test Execution
         │
         ▼
┌─────────────────────────────────┐
│     Failure Analyzer (Day 9)    │  ──> FailureAnalysisResult (root cause, failure category)
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│  Healing Decision Engine (Day 10) │
│  ┌───────────────────────────┐  │
│  │ 1. Safety Rules Guardrail │  │  ──> Blocks ASSERTION_FAILED, NETWORK_ERROR, etc.
│  └─────────────┬─────────────┘  │
│                ▼                │
│  ┌───────────────────────────┐  │
│  │ 2. Candidate Generation   │  │  ──> Sources: Current DOM elements + Historical Healing records
│  └─────────────┬─────────────┘  │
│                ▼                │
│  ┌───────────────────────────┐  │
│  │ 3. Multi-Signal Scoring   │  │  ──> Deterministic weights (text, role, page, type, history)
│  └─────────────┬─────────────┘  │
│                ▼                │
│  ┌───────────────────────────┐  │
│  │ 4. Ranking & Thresholds   │  │  ──> HIGH (≥0.80), MEDIUM (≥0.50), LOW (<0.50), MIN (0.30)
│  └─────────────┬─────────────┘  │
│                ▼                │
│  ┌───────────────────────────┐  │
│  │ 5. Optional LLM Disambig  │  │  ──> Invoked only if top candidate scores are tied / close
│  └─────────────┬─────────────┘  │
└────────────────┬────────────────┘
                 │
                 ▼
       HealingRecommendation
                 │
                 ▼
┌─────────────────────────────────┐
│ recommendation_to_healing_      │  ──> Bridges Member 1 recommendation to Member 2 contract
│          candidate()            │
└────────────────┬────────────────┘
                 │
                 ▼
          HealingCandidate
                 │
                 ▼
┌─────────────────────────────────┐
│   Member 2 Execution Engine     │  ──> Browser validation in Playwright (runs proposed selector)
└────────────────┬────────────────┘
                 │
                 ▼
            HealingResult
                 │
                 ▼
┌─────────────────────────────────┐
│ healing_result_to_memory_       │  ──> Formats validated outcome for persistent memory storage
│          update()               │
└────────────────┬────────────────┘
                 │
                 ▼
     MemoryStore.store_healing_
               record()
```

### Key Components & Capabilities:
- **Strict Architecture Boundaries**:
  - Member 1's role is strictly **decision-making, candidate generation, and scoring**.
  - Does **NOT** execute browser actions or directly modify selectors in Playwright (Member 2's domain).
  - All recommendations enforce `requires_validation = True`.
- **Multi-Source Candidate Generation (`CandidateGenerator`)**:
  - **Current UI Elements**: Compares visible elements on the current page against failed element snapshots using text, semantic role, element type, page URL/title, and name similarity.
  - **Historical Healing Records**: Queries `MemoryStore.get_healing_history()` to locate previously verified selector replacements for identical failed targets.
- **Weighted Multi-Signal Candidate Scoring (`CandidateScorer`)**:
  - Deterministic evaluation using configurable `ScoringWeights`:
    - **Visible Text Match** (`0.30`): Strong signal for UI button/link labels.
    - **Semantic / ARIA Role** (`0.25`): Ensures structural element parity (`button`, `textbox`, etc.).
    - **Page Context** (`0.15`): Matches current page URL or title.
    - **Historical Similarity** (`0.15`): Bonus boost for proven historical fixes.
    - **Element Type** (`0.10`): Compares HTML tag names (`input`, `a`, `button`).
    - **Name Attribute** (`0.05`): Matches form input `name` attributes.
  - *Calibrated Design*: A complete match on observable DOM attributes achieves `0.85` (HIGH confidence) without requiring historical records.
- **Confidence Thresholds & Safety Rules**:
  - Evaluates candidates against calibrated levels: `HIGH` (≥ 0.80), `MEDIUM` (≥ 0.50), `LOW` (< 0.50). Candidates below `0.30` are rejected.
  - **Safety Guardrails**: Automatically blocks healing (`DO_NOT_HEAL`) for `ASSERTION_FAILED` (business logic failures), `NETWORK_ERROR` (infrastructure), and `APPLICATION_ERROR` (backend bugs).
- **Action Mapping Matrix (`HealingAction`)**:
  - `TRY_REPLACEMENT_SELECTOR`: Clear top candidate meets confidence threshold.
  - `SEARCH_CURRENT_UI`: Candidates exist but confidence is low; broader UI search recommended.
  - `REQUIRE_FURTHER_ANALYSIS`: No viable candidates or unclassifiable failure.
  - `DO_NOT_HEAL`: Non-healable failure category or confidence below minimum threshold.
- **Selective LLM Disambiguation**:
  - LLM is only queried if multiple high-ranking candidates tie or score within `0.1` of each other, preserving fast deterministic performance for clear-cut matches.
- **Member 1 ↔ Member 2 Contract Bridge (`agents/healer/healing_result_mapper.py`)**:
  - `recommendation_to_healing_candidate()` converts `HealingRecommendation` into the `HealingCandidate` schema consumed by Member 2.
  - `healing_result_to_memory_update()` translates Member 2's post-execution `HealingResult` into a `HealingRecord` to update `MemoryStore`.
- **50 Comprehensive Tests (`tests/test_day10_healing_decision.py`)**:
  - Validates schemas, context aggregation, candidate generation, scoring weights, ranking, confidence calibration, safety rules, LLM disambiguation, and Member 2 bridge mappings.
  - Test suite expanded from 593 to **643 passing tests** (100% offline, 0 failures, 0 regressions).

---

## 🧠 AI-Assisted Healing Decision & Candidate Ranking (Day 11)

Building on Day 10's foundation, **Day 11** advances Member 1's intelligence layer with **stable attribute evidence**, **ambiguity detection**, **AI-assisted candidate evaluation (`LLMHealingEvaluator`)** with strict **grounding validation**, and a complete **HealingDecision lifecycle**.

```
Failed Test
     │
Failure Analyzer (Day 9)
     │
FailureAnalysis + Historical Context
     │
Candidate Generator (Day 10 + Day 11)
     │ (DOM + History + Stable Attributes: data-testid, aria-label, etc.)
Candidates with Observable Evidence
     │
Candidate Scorer (Deterministic Multi-Signal Scoring)
     │
Candidate Ranking (Highest Confidence First)
     │
Ambiguity Detection (Gap ≤ ambiguity_threshold?)
    ├── NO  ──> Select Top Candidate ──> Classify Decision
    └── YES ──> Is LLM Available?
                 ├── YES ──> LLMHealingEvaluator
                 │            ├── Structured Prompt (Observable Evidence Only)
                 │            ├── Response Normalization & Schema Validation
                 │            └── Grounding Validation (Selector in Context?)
                 │                 ├── VALID   ──> Resolved Candidate
                 │                 └── INVALID ──> Escalate / Fallback
                 └── NO  ──> REQUIRE_FURTHER_ANALYSIS
     │
Final HealingRecommendation (with HealingDecision)
     │
Member 1 ↔ Member 2 Contract Bridge
     │
Member 2 (Browser Execution & Validation)
     │
prepare_healing_result()
     │
HealingResult ──> MemoryStore Update
```

### Key Capabilities (Day 11):
- **Stable Attribute Evidence & Similarity**:
  - Automatically identifies and compares resilient HTML attributes (`data-testid`, `data-test-id`, `data-qa`, `data-cy`, `aria-label`, `aria-labelledby`, `class`).
  - Emits observable evidence: `Matching stable attributes: data-testid`.
  - Configurable `stable_attribute_weight` dimension in `ScoringWeights`.
- **Candidate Ranking**:
  - Sorts all candidates deterministically by confidence score.
  - Preserves separation between recommendation generation and execution (Member 1 recommends, Member 2 executes).
- **Ambiguity Detection**:
  - Detects when the score gap between top candidates is $\le$ `ambiguity_threshold` (default `0.05`).
  - Prevents making arbitrary choices when candidates are too close; routes to `REQUIRE_FURTHER_ANALYSIS` or optional LLM evaluation.
- **LLM Healing Evaluator with Strict Grounding Validation (`LLMHealingEvaluator`)**:
  - Accepts only structured observable evidence (failure type, target selector, candidate list, visible text, roles, attributes).
  - Prompts model for structured JSON: `{"selected_candidate": "...", "confidence": 0.95, "reason": "..."}`.
  - **Zero Hallucinations**: Deterministic grounding check verifies the selected selector exists in the provided candidates; rejects invented or out-of-context selectors.
  - No chain-of-thought stored; outputs are clean and independently auditable.
- **High-Level Healing Decision Lifecycle (`HealingDecision`)**:
  - `RECOMMEND_HEALING`: Clear winner with high confidence ($\ge 0.80$).
  - `REQUIRE_VALIDATION`: Viable candidate with medium confidence ($0.50 \le \text{score} < 0.80$).
  - `REQUIRE_FURTHER_ANALYSIS`: Ambiguous candidates or low confidence ($0.30 \le \text{score} < 0.50$).
  - `DO_NOT_HEAL`: Non-healable failure types (`ASSERTION_FAILURE`, `NETWORK_ERROR`, `APPLICATION_ERROR`), no candidates, or score $< 0.30$.
- **Member 2 Inter-Member Contract**:
  - Formalized input/output contracts documented in `agents/healer/healing_result_mapper.py`.
  - `prepare_healing_result()` convenience helper transforms Member 2's post-execution feedback into a standardized `HealingResult` ready for `MemoryStore` ingestion.
- **45 Comprehensive Day 11 Tests (`tests/test_day11_healing_intelligence.py`)**:
  - Unit tests for stable attributes, deterministic scoring, ranking, thresholds, ambiguity detection, decision mapping, and grounding validation.
  - 6 end-to-end scenarios: Clear Winner, Ambiguous, Low Confidence, Invalid LLM Candidate Rejection, Valid LLM Recommendation, and No Candidates.
  - Full pipeline integration test: Memory $\to$ Analyzer $\to$ Candidate Generator $\to$ Scorer $\to$ Decision Engine $\to$ Member 2 Bridge.
  - Test suite expanded from 643 to **688 passing tests** (100% offline, 0 failures, 0 regressions).

---

## 🔄 Healing Result Feedback & Memory Learning (Day 12)

Building on Day 11's AI-assisted decision making, **Day 12** closes the self-healing feedback loop by introducing **Healing Result Feedback & Memory Learning**. The platform now dynamically learns from execution outcomes: Member 2's browser validation results feed directly into Member 1's historical memory, continually updating selector stability scores, tracking replacement history, and detecting recurring failure patterns.

```
Failed Test
     │
Failure Analyzer (Day 9)
     │
Candidate Generator (Day 10 + 11) ◄── Historical Evidence (Day 12)
     │                                 (ReplacementStats, SelectorHistory,
     │                                  Stability Scores, Success Rates)
Candidate Scorer (Deterministic Multi-Signal + History)
     │
Candidate Ranking & Ambiguity Detection
     │
Healing Decision Engine (Day 11)
     │
HealingRecommendation
     │
Member 2 (Browser Execution & Validation)
     │
HealingResultFeedback (Day 12)
  ├── validation_status (SUCCESS / FAILED / TIMEOUT / ERROR)
  ├── execution_time_ms, attempts, error_message
  └── dom_snapshot, screenshot_path
     │
HealingResultFeedbackProcessor (Day 12)
  ├── Ingests validation outcome
  ├── Stores structured HealingRecord in MemoryStore
  ├── Updates selector stability & replacement frequencies
  └── Feeds into HealingPatternDetector
```

### Key Capabilities (Day 12):
- **Structured Validation Feedback Contract (`HealingResultFeedback`)**:
  - Pydantic v2 data contract capturing Member 2 post-validation execution results.
  - Fields: `healing_id`, `test_id`, `original_selector`, `healed_selector`, `validation_status` (`SUCCESS`, `FAILED`, `TIMEOUT`, `ERROR`, `SKIPPED`), `execution_time_ms`, `attempts`, `error_message`, `dom_snapshot`, `screenshot_path`, `validated_at`.
  - Backwards-compatible `to_healing_result()` converter to produce legacy `HealingResult` objects.
- **Feedback Ingestion & State Updating (`HealingResultFeedbackProcessor`)**:
  - Ingests validation outcomes into `MemoryStore` as structured `HealingRecord`s.
  - Dynamically updates selector stability tallies and replacement counts.
  - Emits observable feedback summary events for auditability and real-time observability.
- **Historical Evidence Retrieval (`HealingEvidenceRetriever`)**:
  - Aggregates historical performance of proposed replacements before scoring.
  - Queries `MemoryStore` for `ReplacementStats` (total attempts, success rate, last used timestamp).
  - Queries `SelectorHistory` (breakage count, known replacements, overall stability score).
  - Populates `healing_history_score` on candidate selectors to favor historically verified replacements.
- **Healing Pattern Detection (`HealingPatternDetector`)**:
  - Analyzes historical healing and failure records across tests to identify systemic UI fragility.
  - Detects `REPEATED_SELECTOR_FAILURE`, `FREQUENT_BREAKAGE`, `FLAKY_SELECTOR`, and `STABLE_REPLACEMENT`.
  - Generates actionable insights with confidence scores and recommendations for test maintenance.
- **Closed-Loop Candidate Scoring Integration**:
  - `ScoredCandidate` enhanced with `healing_history_score`.
  - Configurable `healing_history_weight` in `ScoringWeights` (defaults to `0.0` for backwards compatibility, configurable for active learning).
  - `HealingDecisionEngine` enriches candidates with historical evidence during decision making.
- **50 Comprehensive Day 12 Tests (`tests/test_day12_healing_feedback.py`)**:
  - Validation feedback ingestion & processor tests.
  - Healing evidence retrieval & replacement statistics tests.
  - Pattern detector tests (repeated failure, flaky selector, stable replacement).
  - Closed-loop feedback cycle tests (decision $\to$ validation $\to$ feedback $\to$ memory $\to$ learned candidate scoring).
  - Test suite expanded from 688 to **738 passing tests** (100% offline, 0 failures, 0 regressions).

---

## 🤖 Autonomous AI Agent Orchestrator (Day 13)

Building on Days 1–12, **Day 13** connects the intelligence components into an end-to-end autonomous orchestration workflow. The `AgentOrchestrator` implements an explicit finite state machine that coordinates:
**Test Planning** $\to$ **Test Execution Result** $\to$ **Failure Analysis** $\to$ **Historical Memory** $\to$ **Self-Healing Decision** $\to$ **Validation Feedback Ingestion** $\to$ **Memory Learning**.

```
                           ┌───────────────────────────┐
                           │      WorkflowStep.IDLE    │
                           └─────────────┬─────────────┘
                                         │ start_planning()
                                         ▼
                           ┌───────────────────────────┐
                           │   WorkflowStep.PLANNING   │
                           └─────────────┬─────────────┘
                                         │ TestPlan generated
                                         ▼
                           ┌───────────────────────────┐
                           │    WorkflowStep.PLANNED   │
                           └─────────────┬─────────────┘
                                         │ (handoff to Member 2)
                                         ▼
                           ┌───────────────────────────┐
                           │   WorkflowStep.EXECUTING  │
                           └─────────────┬─────────────┘
                                         │
                    ┌────────────────────┴────────────────────┐
     submit_execution_result(PASSED)            submit_execution_result(FAILED)
                    │                                         │
                    ▼                                         ▼
      ┌───────────────────────────┐             ┌───────────────────────────┐
      │   WorkflowStep.COMPLETED  │             │   WorkflowStep.ANALYZING  │
      └───────────────────────────┘             └─────────────┬─────────────┘
                                                              │ Root cause diagnosed
                                                              ▼
                                                ┌───────────────────────────┐
                                                │   WorkflowStep.ANALYZED   │
                                                └─────────────┬─────────────┘
                                                              │
                                       ┌──────────────────────┴──────────────────────┐
                             Non-healable failure                           Healable failure
                                       │                                             │
                                       ▼                                             ▼
                         ┌───────────────────────────┐                 ┌───────────────────────────┐
                         │    WorkflowStep.FAILED    │                 │    WorkflowStep.HEALING   │
                         └───────────────────────────┘                 └─────────────┬─────────────┘
                                                                                     │ Recommendation made
                                                                                     ▼
                                                                       ┌───────────────────────────┐
                                                                       │     WorkflowStep.HEALED   │
                                                                       │  (or NO_HEALING_AVAILABLE)│
                                                                       └─────────────┬─────────────┘
                                                                                     │ (handoff to Member 2)
                                                                                     ▼
                                                                       ┌───────────────────────────┐
                                                                       │   WorkflowStep.VALIDATING │
                                                                       └─────────────┬─────────────┘
                                                                                     │ submit_healing_result()
                                                                                     ▼
                                                                       ┌───────────────────────────┐
                                                                       │ WorkflowStep.FEEDBACK_REC │
                                                                       └─────────────┬─────────────┘
                                                                                     │
                                                      ┌──────────────────────────────┴──────────────────────────────┐
                                            Validation SUCCESS                                             Validation FAILED
                                                      │                                                             │
                                                      ▼                                                             ▼
                                        ┌───────────────────────────┐                                 ┌───────────────────────────┐
                                        │   WorkflowStep.COMPLETED  │                                 │ Retries < max_healing_att?│
                                        └───────────────────────────┘                                 └──────┬─────────────┬──────┘
                                                                                                       YES   │             │ NO
                                                                                                             ▼             ▼
                                                                                                      [Re-enter HEALING] [FAILED]
```

### Key Capabilities (Day 13):

- **Explicit Finite State Machine (`WorkflowStep` & `VALID_TRANSITIONS`)**:
  - 13 strongly-typed lifecycle steps: `IDLE`, `PLANNING`, `PLANNED`, `EXECUTING`, `ANALYZING`, `ANALYZED`, `HEALING`, `HEALED`, `VALIDATING`, `FEEDBACK_RECEIVED`, `COMPLETED`, `FAILED`, `NO_HEALING_AVAILABLE`.
  - Compile-time and runtime validation of transitions through `VALID_TRANSITIONS`. Invalid transitions are rejected with descriptive `ValueError`s.
- **Comprehensive Workflow Schemas (`agents.orchestration.workflow_schemas`)**:
  - `AgentState`: 26 typed fields maintaining end-to-end execution context (`session_id`, `step`, `plan`, `execution_result`, `analysis_result`, `healing_recommendation`, `validation_feedback`, `healing_attempts`, `events`, `metadata`, etc.).
  - `ExecutionResult`: Member 2 execution handoff contract with `ExecutionResultStatus` (`PASSED`, `FAILED`, `ERROR`, `TIMEOUT`, `SKIPPED`), step results, duration, error messages, and DOM context snapshot.
  - `WorkflowEvent`: Structured event logging with `WorkflowEventType`, timestamp, from/to steps, details, and message.
  - `OrchestratorConfig`: Configurable settings for `max_healing_attempts` (default: 3), `auto_learn_on_feedback`, `history_weight`, `strict_mode`, and `store_execution_records`.
- **Autonomous Lifecycle Coordination (`AgentOrchestrator`)**:
  - `start_planning(app_context)`: Triggers `TestPlannerAgent`, stores generated `TestPlan` in `AgentState`, and transitions to `PLANNED`.
  - `submit_execution_result(result, app_context)`: Ingests Member 2 execution outcomes. If `PASSED`, transitions to `COMPLETED`. If `FAILED`, invokes `FailureAnalysisAgent` (root cause, confidence, evidence), transitions through `ANALYZING` $\to$ `ANALYZED`, and automatically triggers `HealingDecisionEngine` if eligible.
  - `submit_healing_result(feedback, app_context)`: Ingests Member 2 healing validation feedback. Automatically invokes `HealingResultFeedbackProcessor` to update `MemoryStore` stability and replacement stats. On `SUCCESS`, transitions to `COMPLETED`. On failure with remaining budget, safely loops back to `HEALING` or transitions to `FAILED`.
  - `get_state()`: Provides inspection of current state, transition history, and audit log.
- **Safety Constraints & Resilience**:
  - Configurable `max_healing_attempts` prevents infinite healing loops.
  - Strict input validation: non-healable failures (`BUG`, `ENVIRONMENT_ISSUE`) terminate cleanly in `FAILED`.
  - Missing DOM or recommendations safely transition to `NO_HEALING_AVAILABLE`.
  - Safe error recovery without crashing the host process.
- **61 Comprehensive Day 13 Tests (`tests/test_day13_agent_orchestrator.py`)**:
  - State machine transitions & transition validation.
  - Test planning flow & error handling.
  - Execution result handling (pass, fail, healable vs non-healable).
  - End-to-end healing lifecycle (analyze $\to$ heal $\to$ validate $\to$ learn).
  - Retry handling and max attempts limits.
  - Memory recording & feedback processor integration.
  - Edge cases, safety guards, and contract integrity.
  - Test suite expanded from 738 to **799 passing tests** (100% offline, 0 failures, 0 regressions).

---

## 🎯 Autonomous Recovery Policy & Explainable Decisions (Day 14)

The **Autonomous Recovery Policy** layer introduces governance, deterministic decision-making, and auditability to the self-healing and recovery process. It ensures the AI agent does not blindly attempt healing for every failure, prevents infinite loops, handles transient errors gracefully, and provides clear, evidence-backed explanations for every decision.

```
                  Failure Detected
                         │
                         ▼
             ┌───────────────────────┐
             │ FailureAnalyzerAgent  │
             └───────────┬───────────┘
                         │ FailureAnalysis
                         ▼
             ┌───────────────────────┐
             │    RecoveryPolicy     │ ── Evaluates failure type, attempt count,
             │                       │    retry count, and candidate evidence
             └───────────┬───────────┘
                         │
        ┌────────────────┼────────────────┬────────────────┐
        │                │                │                │
        ▼                ▼                ▼                ▼
   TRY_HEALING         RETRY            ABORT         DO_NOT_HEAL
 (healable type,   (transient:       (attempts       (assertion fail,
  conf >= 0.80,    TIMEOUT, NAV,     >= max or       low confidence,
  Member 2 val)    retries < max)    exhausted)      ambiguous, etc.)
```

### Key Capabilities (Day 14):

- **Recovery Actions (`RecoveryAction`)**:
  - `TRY_HEALING`: Execute self-healing with the top-ranked candidate selector (requires Member 2 browser validation).
  - `RETRY`: Re-execute the step/test case for transient failures (`TIMEOUT`, `NAVIGATION_FAILURE`, `ELEMENT_NOT_INTERACTABLE`) up to `max_retries`.
  - `ESCALATE`: Escalate to human operator or higher-tier diagnostic agent when automated recovery is infeasible.
  - `ABORT`: Halt execution cleanly when `max_healing_attempts` or `max_retries` is exceeded, or when all candidates are exhausted.
  - `DO_NOT_HEAL`: Skip healing when the failure type is explicitly non-healable (e.g. `ASSERTION_FAILURE`, `APPLICATION_ERROR`), when confidence is below threshold, or when top candidates are ambiguous.
  - `REQUIRE_FURTHER_ANALYSIS`: Defer recovery when diagnostic confidence is low or root cause is unknown.
- **Explainable Decision Model (`RecoveryDecision`)**:
  - Fully typed Pydantic contract capturing `workflow_id`, `test_case_id`, `failure_type`, `decision`, `confidence`, `selected_candidate`, `reason`, `evidence`, `attempt_number`, `retry_count`, `requires_validation`, and `next_state`.
  - Structured, human-readable reason and observable evidence list for complete auditability.
- **Configurable Recovery Governance (`RecoveryPolicyConfig` & `FailureTypePolicy`)**:
  - `max_healing_attempts` (default: 3) and `max_retries` (default: 2) enforce strict execution bounds.
  - `min_healing_confidence` (default: 0.80) and `min_candidate_score` (default: 0.30) enforce high standards before attempting changes.
  - `ambiguity_margin` (default: 0.05) detects when multiple candidate selectors have nearly identical scores and flags for human or further analysis.
  - `history_boost_weight` (default: 0.15) modulates candidate confidence based on historical replacement success rates from `HealingEvidenceRetriever`.
  - Per-failure-type policy matrix (`_DEFAULT_FAILURE_POLICIES`) dictating whether a failure is healable, retryable, and its retry limit.
- **Comprehensive Policy Evaluation (`RecoveryPolicy`)**:
  - `evaluate()`: Initial multi-stage evaluation pipeline (attempt limits, failure-type policy, transient retry check, candidate filtering, ambiguity detection, historical weighting, threshold check).
  - `evaluate_continuation()`: Post-validation continuation check when Member 2 reports a healing failure, intelligently selecting the next best unattempted candidate or cleanly aborting.
- **Workflow & Orchestrator Integration**:
  - Extended `WorkflowStep` with `RETRYING` state and valid transitions (`ANALYZING_FAILURE -> RETRYING -> EXECUTION_PENDING`).
  - Extended `WorkflowEventType` with `RECOVERY_DECISION_CREATED` and `RETRY_INITIATED`.
  - Integrated with `AgentOrchestrator` (`_recovery_policy`, `AgentState.recovery_decision`, `AgentState.retry_count`, `AgentState.max_retries`).
  - Exported through `agents.schemas.contracts` for shared Member 1 $\leftrightarrow$ Member 2 $\leftrightarrow$ Member 3 access.
- **83 Comprehensive Day 14 Tests (`tests/test_day14_recovery_policy.py`)**:
  - Unit tests for all failure types, retry escalation, duplicate candidate suppression, ambiguity handling, historical evidence boosts, explainability, safety invariants, and determinism.
  - Total test suite expanded to **882 passing tests** (100% offline, 0 failures, 0 regressions).

---

## 📂 Project Structure (`agents/`)

```
.
├── agents/
│   ├── analyzer/              # Failure Analysis Agent & Schemas (Day 9)
│   │   ├── analyzer.py        # FailureAnalysisAgent ABC + RuleBasedFailureAnalyzer
│   │   └── schemas.py         # FailureContext, FailureAnalysisResult, FailureEvidence, etc.
│   ├── healer/                # Self-Healing Decision Layer (Day 10 + Day 11 + Day 12)
│   │   ├── candidate_generator.py # Candidate generation from DOM & historical memory + stable attrs
│   │   ├── candidate_scorer.py# Weighted candidate scoring, ranking & confidence thresholds
│   │   ├── healing_decision.py# HealingDecisionEngine orchestrator & ambiguity detection
│   │   ├── healing_feedback.py# HealingResultFeedback & processor for Member 2 feedback (Day 12)
│   │   ├── healing_result_mapper.py # Member 1 ↔ Member 2 contract bridge & prepare_healing_result()
│   │   ├── healing_schemas.py # ScoredCandidate, HealingRecommendation, HealingContext, LLMEvaluationResult
│   │   ├── llm_healing_evaluator.py # AI-assisted candidate evaluation with strict grounding validation (Day 11)
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
│   ├── memory/                # Historical Memory & Context Management (Day 8 + Day 12)
│   │   ├── context_comparator.py # Element diff engine (added, removed, modified elements)
│   │   ├── healing_evidence.py# HealingEvidenceRetriever & ReplacementStats (Day 12)
│   │   ├── healing_history.py # Abstract HealingMemory interface (legacy compatibility)
│   │   ├── in_memory_store.py # InMemoryStore with filtering, snapshots & query helpers
│   │   ├── memory_interface.py# Storage-independent MemoryStore ABC
│   │   ├── memory_schemas.py  # TestExecutionRecord, FailureInfo, ElementRecord, HealingRecord
│   │   └── pattern_detector.py# HealingPatternDetector for recurring selector patterns (Day 12)
│   ├── orchestration/         # Autonomous Agent Orchestration & Recovery Policy (Day 13 + Day 14)
│   │   ├── agent_controller.py# Abstract AgentController
│   │   ├── agent_orchestrator.py# AgentOrchestrator state machine coordinating Plan → Execute → Analyze → Heal → Validate
│   │   ├── recovery_policy.py # Autonomous Recovery Policy & Explainable Decisions (Day 14)
│   │   └── workflow_schemas.py# WorkflowStep, AgentState, ExecutionResult, WorkflowEvent, OrchestratorConfig
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
│       └── enums.py           # FailureType, HealingStatus, TestPriority, TestCategory, TestAction, AssertionType, ExecutionStatus, ChangeType, FailureCategory, ConfidenceLevel, HealingAction, CandidateSource, HealingDecision, ValidationStatus, HealingPatternType
├── docs/
│   └── member1-architecture.md# Comprehensive architectural specification (v0.11.0)
├── tests/
│   ├── test_config.py             # Config loading & immutability tests
│   ├── test_day6_response_validation.py # Day 6 response validation & hardening (41 tests)
│   ├── test_day7_langchain_integration.py # Day 7 LangChain integration tests (95 tests)
│   ├── test_day8_memory.py        # Day 8 historical memory & context comparator tests (57 tests)
│   ├── test_day9_failure_analyzer.py # Day 9 failure analyzer agent & diagnostic tests (61 tests)
│   ├── test_day10_healing_decision.py # Day 10 self-healing decision & candidate generator tests (50 tests)
│   ├── test_day11_healing_intelligence.py # Day 11 AI-assisted healing decision & candidate ranking tests (45 tests)
│   ├── test_day12_healing_feedback.py # Day 12 healing result feedback & memory learning tests (50 tests)
│   ├── test_day13_agent_orchestrator.py # Day 13 AI agent orchestrator & workflow coordination tests (61 tests)
│   ├── test_day14_recovery_policy.py # Day 14 autonomous recovery policy & explainable decisions (83 tests)
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
- [x] **Day 10**: Self-Healing Decision Layer & Candidate Generation foundation: candidate generation (DOM + history), weighted multi-signal scoring, confidence thresholds, safety rules, action mapping, optional LLM disambiguation, Member 1 ↔ Member 2 contract bridge, and 50 tests (643 tests total).
- [x] **Day 11**: AI-Assisted Healing Decision & Candidate Ranking: `LLMHealingEvaluator` with strict DOM grounding, ambiguity detection, stable attribute evidence, confidence-calibrated decision engine, and 45 tests (688 tests total).
- [x] **Day 12**: Healing Result Feedback & Memory Learning: validation feedback ingestion (`HealingResultFeedback`, `HealingResultFeedbackProcessor`), historical evidence retrieval (`HealingEvidenceRetriever`), pattern detection (`HealingPatternDetector`), feedback loop enrichment in `HealingDecisionEngine`, and 50 tests (738 tests total).
- [x] **Day 13**: Autonomous AI Agent Orchestrator: end-to-end workflow state machine (`AgentOrchestrator`, `WorkflowStep`, `AgentState`), coordination across Planner, Failure Analyzer, Healer, Memory, and Validation, safety constraints (max attempts, terminal states), structured event audit trail, and 61 tests (799 tests total).
- [x] **Day 14**: Autonomous Recovery Policy & Explainable Agent Decisions: deterministic recovery actions (`RecoveryAction`), explainable decision model (`RecoveryDecision`), configurable governance (`RecoveryPolicyConfig`, `FailureTypePolicy`), multi-stage policy evaluator (`RecoveryPolicy`), `WorkflowStep.RETRYING`, audit events (`RECOVERY_DECISION_CREATED`, `RETRY_INITIATED`), orchestrator integration, and 83 tests (882 tests total).
- [ ] **Day 15**: Persistent Healing Memory & Vector Storage integration.
- [ ] **Day 16–18**: Full pipeline orchestration & integration with Member 2 & 3.



