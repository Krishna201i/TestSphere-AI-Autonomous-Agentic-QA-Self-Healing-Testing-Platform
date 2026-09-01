# TestSphere-AI: Autonomous Agentic QA & Self-Healing Testing Platform

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Pydantic](https://img.shields.io/badge/Pydantic-v2-e92063.svg)](https://docs.pydantic.dev/)
[![Tests](https://img.shields.io/badge/Tests-152%20Passed-brightgreen.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**TestSphere-AI** is an intelligent, multi-agent autonomous testing platform designed to plan, generate, execute, analyze, and self-heal end-to-end web application tests.

---

## 👥 Team Responsibilities & Division of Labor

- **Member 1 (AI Agent & Intelligence Layer - `vinamra-branch`)**:
  - LLM integration & provider-independent client abstraction (`LLMClientSession`, `LLMClient`)
  - Test Planner Agent (test generation & prioritization)
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
│     Test Planner Agent    │  ──> Generates structured TestCase models
└─────────────┬─────────────┘
              │
              ▼
        list[TestCase]
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

## 🤖 LLM Client Architecture (Day 2 & Day 3 Foundation)

All AI agents interact with models strictly through the provider-independent `LLMClientSession` and `LLMClient` interfaces:

```
                ┌───────────────────┐
                │   FUTURE AGENTS   │
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
- **Error Hierarchy**: 8 granular exception types rooted in `LLMError` with `is_retryable` property.
- **Mock Response Registry**: Flexible offline mocking by prompt pattern matching, custom error injection, and transient failure sequence testing.
- **Zero Secrets Logged / Committed**: Strict safeguards ensure credentials and raw API keys are never logged or committed.

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
│   │   ├── exceptions.py      # LLM exception hierarchy (8 types + is_retryable)
│   │   ├── factory.py         # Provider factory (get_llm_provider, create_llm_client)
│   │   ├── parser.py          # ResponseParser (text, JSON, Pydantic model validation)
│   │   ├── schemas.py         # LLMRequest, LLMResponse, LLMUsage models + validators
│   │   └── providers/
│   │       └── mock.py        # MockLLMProvider with simulations & response registry
│   ├── memory/                # Healing Memory Store
│   │   └── healing_history.py # Abstract HealingMemory interface
│   ├── orchestration/         # Pipeline Controller
│   │   └── agent_controller.py# Abstract AgentController
│   ├── planner/               # Test Planner Agent & Schemas
│   │   ├── planner.py         # Abstract TestPlannerAgent
│   │   └── schemas.py         # ApplicationContext, TestCase, TestStep, Assertion
│   └── schemas/               # Shared Enums & Data Contracts
│       ├── contracts.py       # Re-exported single source of truth
│       └── enums.py           # FailureType, HealingStatus, TestPriority, TestCategory
├── docs/
│   └── member1-architecture.md# Comprehensive architectural specification (v0.3.0)
├── tests/
│   ├── test_config.py             # Config loading & immutability tests
│   ├── test_imports.py            # Module import validation tests
│   ├── test_llm_client.py         # Day 2 LLM foundation & mock provider tests
│   ├── test_llm_client_session.py # Day 3 LLM client session & integration tests
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
- [ ] **Day 4–5**: Test Planner Agent implementation & test generation prompt engineering.
- [ ] **Day 6–8**: Failure Analyzer Agent & root cause classification.
- [ ] **Day 9–12**: Self-Healing Agent & semantic DOM selector ranking.
- [ ] **Day 13–15**: Persistent Healing Memory store.
- [ ] **Day 16–18**: Full pipeline orchestration & integration with Member 2 & 3.
