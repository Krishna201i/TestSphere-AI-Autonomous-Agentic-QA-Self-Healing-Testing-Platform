# TestSphere-AI: Autonomous Agentic QA & Self-Healing Testing Platform

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Pydantic](https://img.shields.io/badge/Pydantic-v2-e92063.svg)](https://docs.pydantic.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**TestSphere-AI** is an intelligent, multi-agent autonomous testing platform designed to plan, generate, execute, analyze, and self-heal end-to-end web application tests.

---

## 👥 Team Responsibilities & Division of Labor

- **Member 1 (AI Agent & Intelligence Layer - `vinamra-branch`)**:
  - LLM integration & client abstraction
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
│   ├── llm/                   # LLM Client Abstraction & Config
│   │   ├── client.py          # Abstract LLMClient
│   │   └── config.py          # LLMConfig (env-based configuration)
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
│   └── member1-architecture.md# Comprehensive architectural specification
├── tests/
│   ├── test_config.py         # Config loading & immutability tests
│   ├── test_imports.py        # Module import validation tests
│   └── test_schemas.py        # Pydantic schema validation tests
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
# Edit .env with your LLM credentials (e.g. LLM_API_KEY)
```

### 3. Run Tests

```bash
python -m pytest tests/ -v
```

---

## 🗺️ Roadmap

- [x] **Day 1**: Architecture design, Pydantic contracts, agent interfaces, configuration setup, and documentation.
- [ ] **Day 2–3**: Concrete LLM client integrations (OpenAI / Anthropic).
- [ ] **Day 4–5**: Test Planner Agent logic & prompt engineering.
- [ ] **Day 6–8**: Failure Analyzer Agent & root cause classification.
- [ ] **Day 9–12**: Self-Healing Agent & semantic DOM selector ranking.
- [ ] **Day 13–15**: Persistent Healing Memory store.
- [ ] **Day 16–18**: Full pipeline orchestration & integration with Member 2 & 3.
