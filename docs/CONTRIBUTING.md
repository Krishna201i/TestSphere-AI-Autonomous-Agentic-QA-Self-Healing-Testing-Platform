# Contributing to TestSphere-AI

Thank you for your interest in contributing to **TestSphere-AI**! This guide details our development standards, codebase structure, test running procedures, and Git contribution workflow.

---

## 1. Development Environment Setup

### 1.1 Prerequisites
- Python 3.11+ (the version in `backend/.python-version`)
- Git 2.30+
- Node.js 24+ (the dashboard in `frontend/`)

### 1.2 Virtual Environment & Dependencies
```powershell
# Clone the repository
git clone https://github.com/Krishna201i/TestSphere-AI-Autonomous-Agentic-QA-Self-Healing-Testing-Platform.git
cd TestSphere-AI-Autonomous-Agentic-QA-Self-Healing-Testing-Platform

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1   # On Windows
# source .venv/bin/activate  # On macOS/Linux

# Install the exact versions production runs, then the dev tools
# (all Python lives in backend/; run every Python command from there)
cd backend
pip install --upgrade pip
pip install -r requirements.txt
pip install -e ".[dev]"

# Install the Playwright browser the engine uses
playwright install chromium
```

### 1.1 Changing dependencies

`backend/requirements.in` lists the allowed version ranges; `requirements.txt` is the
lock generated from it (exact versions + hashes, for Linux and Windows) and is
what the Docker image installs. Edit `requirements.in`, then regenerate the lock:

```powershell
cd backend
uv pip compile requirements.in --universal --python-version 3.11 --generate-hashes -o requirements.txt
```

Use `--upgrade` (or `--upgrade-package <name>`) to move pinned versions forward.
Run the test suite before committing the new lock.

---

## 2. Testing Guidelines

TestSphere-AI maintains a strict 100% test pass requirement. All new features and bug fixes must include unit or integration tests.

### 2.1 Running the Complete Test Suite
```powershell
cd backend
python -m pytest -v
```

### 2.1a Frontend and end-to-end tests
```powershell
cd frontend; npm test              # Vitest unit/component tests (src/**/*.test.js[x])
npm run build; cd ../backend      # the end-to-end tests drive the built dashboard
python -m pytest tests/e2e         # backend + dashboard in Chromium; skipped if not built
```

### 2.2 Running Subsystem Tests
```powershell
cd backend

# Browser Execution Engine tests
python -m pytest tests/engine/ -v

# Backend & Orchestration tests
python -m pytest tests/app/ -v

# AI Planner & Agent tests
python -m pytest tests/test_planner_pipeline.py tests/test_day10_healing_decision.py -v
```

### 2.3 Offline Testing Guarantee
All unit and integration tests must run fully offline without requiring active API keys or external network connections by utilizing the mock provider (`LLM_PROVIDER=mock`).

---

## 3. Code Standards & Style

We follow modern Python standards:
- **Linting**: `ruff check` from `backend/` must pass (CI runs the rule set in `backend/pyproject.toml`).
- **Type Annotations**: Strict static typing using Python 3.11+ type unions (`str | None`, `list[dict]`).
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
- Ensure the full test suite (`cd backend && python -m pytest`, and `npm test` in `frontend/`) passes before opening a PR.
- Ensure your branch is rebased or cleanly merged with the latest target branch.
- Clearly describe your changes, test results, and any new environment configurations.
