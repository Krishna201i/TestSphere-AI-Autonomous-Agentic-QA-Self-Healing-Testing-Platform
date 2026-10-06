# Contributing to TestSphere-AI

Thank you for your interest in contributing to **TestSphere-AI**! This guide details our development standards, codebase structure, test running procedures, and Git contribution workflow.

---

## 1. Development Environment Setup

### 1.1 Prerequisites
- Python 3.10+ (Python 3.11 recommended)
- Git 2.30+
- Node.js (optional, only for frontend web modules)

### 1.2 Virtual Environment & Dependencies
```powershell
# Clone the repository
git clone https://github.com/Krishna201i/TestSphere-AI-Autonomous-Agentic-QA-Self-Healing-Testing-Platform.git
cd TestSphere-AI-Autonomous-Agentic-QA-Self-Healing-Testing-Platform

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1   # On Windows
# source .venv/bin/activate  # On macOS/Linux

# Install development dependencies
pip install --upgrade pip
pip install -e ".[dev]"

# Install Playwright browser engines
playwright install chromium firefox webkit
```

---

## 2. Testing Guidelines

TestSphere-AI maintains a strict 100% test pass requirement. All new features and bug fixes must include unit or integration tests.

### 2.1 Running the Complete Test Suite
```powershell
python -m pytest tests/engine/ tests/backend/ (Get-ChildItem tests/test_*.py | ForEach-Object { $_.FullName }) -v
```

### 2.2 Running Subsystem Tests
```powershell
# Browser Execution Engine tests
python -m pytest tests/engine/ -v

# Backend & Orchestration tests
python -m pytest tests/backend/ -v

# AI Planner & Agent tests
python -m pytest tests/test_planner_pipeline.py tests/test_healer.py -v
```

### 2.3 Offline Testing Guarantee
All unit and integration tests must run fully offline without requiring active API keys or external network connections by utilizing the mock provider (`LLM_PROVIDER=mock`).

---

## 3. Code Standards & Style

We follow modern Python standards:
- **Formatting**: PEP 8 compliance, formatted via `black` with 100-character line lengths.
- **Type Annotations**: Strict static typing using Python 3.10+ type unions (`str | None`, `list[dict]`).
- **Validation**: Pydantic v2 `BaseModel` for all external schemas and contract boundaries.
- **Docstrings**: Google/Sphinx style docstrings on all public classes, methods, and functions.

---

## 4. Git Branching & Commit Workflow

### 4.1 Commit Message Convention
We adhere to [Conventional Commits](https://www.conventionalcommits.org/):

- `feat(...)`: A new feature or subsystem capability.
- `fix(...)`: A bug fix in existing logic.
- `docs(...)`: Documentation additions or revisions.
- `test(...)`: Adding or updating test suites.
- `refactor(...)`: Code refactoring without behavioral alterations.

### 4.2 Pull Requests
- Ensure all 1,102 tests pass locally before opening a PR.
- Ensure your branch is rebased or cleanly merged with the latest target branch.
- Clearly describe your changes, test results, and any new environment configurations.
