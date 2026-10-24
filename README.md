# TestSphere AI — Member 1: AI Agents & Intelligence

**Owner:** Vinamra Bhatnagar · **Branch:** `vinamra-branch` · **Main folder:** [`agents/`](agents/)

This branch contains the whole TestSphere AI project. This README covers the part Member 1 owns: the AI
agents that plan tests, explain failures and decide whether a healed locator can be trusted. For the overview
of the whole platform, see the [README on `main`](../../tree/main#readme).

---

## What this part does

The platform calls the agents at three points of every run:

1. **Before the run.** The **Test Planner** turns a page analysis and an optional goal into prioritized,
   validated test cases.
2. **When a step fails.** The **Failure Analyzer** classifies why it failed: a broken locator, timing, a
   network problem, an assertion, or an application bug.
3. **When a locator breaks.** The **healing decision engine** scores the candidates the browser engine finds,
   uses the healing memory, and either accepts a heal or refuses it with a reason.

The **agent orchestrator** connects these steps and applies a recovery policy (retry, heal, skip or abort).
Every agent works through a provider-independent **LLM client**, so the whole platform runs offline with the
mock provider and switches to a local or hosted model with one setting.

## Modules

| Module | Contents |
| --- | --- |
| [`agents/planner/`](agents/planner/) | Test Planner: prompts, structured output parsing, validation, prioritization, LangChain adapter, offline mock scenarios |
| [`agents/analyzer/`](agents/analyzer/) | Failure Analyzer and failure classifier |
| [`agents/healer/`](agents/healer/) | Candidate generation and scoring, healing decision, LLM healing evaluator, healing feedback, result mapping |
| [`agents/memory/`](agents/memory/) | Healing history, evidence, pattern detection, context comparison; in-memory and persistent stores |
| [`agents/orchestration/`](agents/orchestration/) | Agent controller, agent orchestrator, recovery policy, workflow schemas |
| [`agents/llm/`](agents/llm/) | LLM client, configuration, response parser, providers (`mock`, `local`, OpenAI-compatible `api`) |
| [`agents/schemas/`](agents/schemas/) | Shared contracts with the engine (Member 2) and the backend (Member 3) |

## Contracts with the other members

- **Engine (Member 2):** [`agents/schemas/member2_contract.py`](agents/schemas/member2_contract.py) defines the
  step results, failure context and healing candidates the engine sends, and the decisions the agents return.
- **Backend (Member 3):** [`agents/schemas/member3_contract.py`](agents/schemas/member3_contract.py) defines the
  test plans and analyses the backend stores and shows in the dashboard.

Changes to these contracts need a matching change on the other side, in the same pull request.

## LLM providers

| `LLM_PROVIDER` | Use |
| --- | --- |
| `mock` (default) | Offline and deterministic. Used by tests and CI. |
| `local` | A local model server such as Ollama (`LLM_BASE_URL`, `LLM_MODEL`) |
| `api` | Any OpenAI-compatible API (`LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`) |

API keys are never logged, and `repr()` masks them.

## Results this part contributes

- **Healing benchmark:** 277 broken-locator cases. The healing decision heals **95.2%** of the cases where
  healing is right, with **0 false heals**, and refuses all the cases where it is wrong
  ([report](docs/healing-benchmark.md)).
- **Failure classification** of real runs is shown on every failed step in the dashboard.

## Working on this part

```bash
pip install -e ".[dev]"
python -m pytest tests/ -q --ignore=tests/backend --ignore=tests/e2e --ignore=tests/engine   # agent tests
python -m engine.heal_benchmark --quick                                                       # healing quality
```

Documentation: [AI agent architecture](docs/member1-architecture.md) ·
[Self-healing & orchestration](docs/self-healing-orchestration.md) · [Integration guide](docs/integration-guide.md)

## How work reaches `main`

1. Branch from `vinamra-branch` or work on it directly.
2. Keep the agent tests and the healing benchmark passing.
3. Open a pull request into `main`. CI runs the full test suite, the security scans and the frontend build.
