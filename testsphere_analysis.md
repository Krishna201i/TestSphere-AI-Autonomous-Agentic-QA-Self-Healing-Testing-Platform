# TestSphere-AI — Codebase Analysis

## What It Is

**TestSphere-AI** is the AI Intelligence Layer for an Autonomous QA / Self-Healing Testing Platform. It is a Python library (`testsphere-ai`, `agents` package) that provides AI-powered test generation, failure analysis, and self-healing — designed to plug into a broader multi-member system where:

- **Member 1** (this repo) = AI Intelligence Layer
- **Member 2** = Test Execution Engine (Playwright-based, external)
- **Member 3** = Backend API (calls into this layer)

---

## Directory Structure

```
TestSphere-AI/
├── agents/                  # Core AI package
│   ├── llm/                 # LLM abstraction layer
│   │   ├── client.py        # LLMClient (ABC) + LLMClientSession (wrapper)
│   │   ├── config.py        # LLMConfig (env-driven settings)
│   │   ├── exceptions.py    # LLMError hierarchy
│   │   ├── factory.py       # create_llm_client() factory
│   │   ├── parser.py        # Response parsing utilities
│   │   ├── schemas.py       # LLMRequest / LLMResponse Pydantic models
│   │   └── providers/
│   │       └── mock.py      # MockLLMProvider (deterministic, test-only)
│   ├── planner/             # Test Planner Agent
│   │   ├── planner.py       # TestPlannerAgent (ABC) + LLMTestPlanner
│   │   ├── schemas.py       # ApplicationContext, TestCase, TestPlan
│   │   ├── prompts.py       # System prompt + prompt builder
│   │   ├── validation.py    # Business-rule validators
│   │   └── mock_scenarios.py# Mock test scenarios for dev/testing
│   ├── analyzer/            # Failure Analyzer Agent
│   │   ├── analyzer.py      # FailureAnalyzerAgent (stub/skeleton)
│   │   └── schemas.py       # TestFailure, FailureAnalysis
│   ├── healer/              # Self-Healing Agent
│   │   ├── healer.py        # SelfHealingAgent (stub/skeleton)
│   │   └── schemas.py       # HealingCandidate, HealingResult
│   ├── memory/              # Healing History Store
│   │   └── healing_history.py # HealingMemory (stub)
│   ├── orchestration/       # Pipeline Coordinator
│   │   └── agent_controller.py # AgentController (ABC, wires agents together)
│   └── schemas/             # Shared contracts
│       ├── enums.py         # FailureType, HealingStatus, TestPriority, TestCategory, TestAction, AssertionType
│       └── contracts.py     # Cross-agent data contracts
├── tests/                   # 10 test files (pytest + pytest-asyncio)
├── docs/
│   └── member1-architecture.md
├── pyproject.toml           # Build config (setuptools, pytest, pydantic, python-dotenv)
└── .env.example
```

---

## Architecture & Data Flow

```
ApplicationContext (input from Member 3)
        ↓
  AgentController.generate_test_plan()
        ↓
  LLMTestPlanner
    ├─ validate_application_context()
    ├─ build_test_generation_prompt()
    ├─ LLMClientSession.generate_json()
    │       ↓
    │   LLMClient (provider)
    │       ↓
    │   MockLLMProvider | future real providers
    ├─ parse response → TestPlan
    ├─ validate_test_case() on each
    ├─ detect_duplicate_test_cases()
    └─ validate_element_references()
        ↓
  list[TestCase] → Member 2 executes

  TestFailure (from Member 2)
        ↓
  AgentController.handle_failure()
        ↓
  FailureAnalyzerAgent.analyze()  → FailureAnalysis
        ↓ (if healable)
  SelfHealingAgent.propose_healing() → HealingCandidate
        ↓
  HealingMemory.record()
```

---

## Key Design Decisions

| Decision | Detail |
|---|---|
| **Provider abstraction** | `LLMClient` ABC decouples all agents from specific LLMs. Only `MockLLMProvider` exists today; real providers (OpenAI, Ollama) are future work. |
| **`LLMClientSession`** | Adds retry, validation, normalization, and error translation on top of the raw provider — agents use this, not the provider directly. |
| **Pydantic v2 everywhere** | `LLMRequest`, `LLMResponse`, `ApplicationContext`, `TestCase`, `TestPlan`, `FailureAnalysis`, `HealingCandidate` are all Pydantic models. |
| **Strict enum vocabulary** | `TestAction` and `AssertionType` enums constrain what the LLM is allowed to generate — Member 2's execution engine maps these 1:1 to Playwright actions. |
| **Graceful degradation** | Invalid/duplicate/hallucinated test cases are logged and filtered, not hard-failures. |
| **`analyzer` / `healer` / `memory` are stubs** | Only `planner` and `llm` are fully implemented. The other agents have correct interfaces (ABCs + schemas) but no LLM logic yet. |

---

## Completeness Status

| Module | Status |
|---|---|
| `agents/llm/` | ✅ Complete — client, config, exceptions, factory, parser, mock provider |
| `agents/planner/` | ✅ Complete — full generation pipeline with validation, dedup, element-ref checks |
| `agents/analyzer/` | 🟡 Skeleton — correct interface + schemas, no LLM logic |
| `agents/healer/` | 🟡 Skeleton — correct interface + schemas, no LLM logic |
| `agents/memory/` | 🟡 Skeleton — `HealingMemory` stub |
| `agents/orchestration/` | 🟡 Skeleton — `AgentController` ABC only, no concrete impl |
| `tests/` | ✅ Good coverage for llm + planner layers (~10 files) |

---

## Notable Issues / Observations

1. **Bug in `_normalize_response`** ([client.py L271](file:///c:/Users/ks759/TestSphere-AI-Autonomous-Agentic-QA-Self-Healing-Testing-Platform/agents/llm/client.py#L271)):
   ```python
   if not response.content and not response.content.strip():
   ```
   The condition is wrong — `and` should be `or`. As written, it only raises if content is both falsy AND whitespace-only (redundant/impossible). Should be:
   ```python
   if not response.content or not response.content.strip():
   ```

2. **No concrete `AgentController`** — the orchestration layer has only an ABC. Member 3's backend can't call it yet.

3. **`healer` and `analyzer` are stubs** — no LLM prompt logic implemented.

4. **Only `MockLLMProvider`** — no real LLM integration yet (no OpenAI, Anthropic, Ollama, etc.).

5. **No async sleep in retry logic** — retries happen immediately with no back-off.
