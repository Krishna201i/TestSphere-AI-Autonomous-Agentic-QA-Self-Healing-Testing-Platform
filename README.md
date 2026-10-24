# TestSphere AI — Autonomous QA & Self-Healing Testing Platform

[![CI](https://github.com/Krishna201i/TestSphere-AI-Autonomous-Agentic-QA-Self-Healing-Testing-Platform/actions/workflows/ci.yml/badge.svg)](https://github.com/Krishna201i/TestSphere-AI-Autonomous-Agentic-QA-Self-Healing-Testing-Platform/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Engine](https://img.shields.io/badge/Engine-Playwright-orange.svg)](https://playwright.dev/)
[![Backend](https://img.shields.io/badge/Backend-FastAPI-teal.svg)](https://fastapi.tiangolo.com/)
[![Frontend](https://img.shields.io/badge/Dashboard-React-61dafb.svg)](https://react.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

TestSphere AI tests a web application end to end on its own. Give it a URL, and optionally a goal in plain
words and a Git repository. It reads the code, plans browser tests, runs them in Chromium, repairs broken
locators while the test runs, scans the site for security weaknesses, and turns fixable findings into a patch
or a pull request for your repository. Each fix is retested, a verified version can be deployed with automatic
rollback, and the whole loop runs again on a schedule or on every push.

---

## The testing loop

```
 1 Codebase ingestion ─▶ 2A AI QA agent ─▶ 2B Attacker agent ─▶ 3 Unified report
          ▲                                                            │
          │                                                            ▼
 6 Verified deploy ◀──────── 5 Validation engine ◀──────────── 4 AI remediation
    (health checks,          (retest; a failed retest           (fix proposals, patches,
     smoke tests, rollback)   goes back to 4)                    pull requests, human approval)
```

| Stage | What it does |
| --- | --- |
| **1. Codebase ingestion** | Clones a public repository (or reads a local folder in development) and builds a blueprint: languages, frameworks, dependencies, existing test suites, HTTP routes, committed secrets and debug flags. Nothing in the repository is executed. |
| **2A. AI QA agent** | Analyzes the live page (rendering JavaScript apps in a real browser), turns the written goal into steps using the values it contains, plans smoke, scenario, content and linked-page tests, and runs them in Playwright. |
| **Self-healing** | When a locator breaks, the engine tries stored fallbacks, then a fingerprint scan of the live DOM, scoring attributes, text, position and structure. It refuses look-alikes and elements whose kind changed. |
| **2B. Attacker agent** | Passive, scope-checked security scan: headers, cookies, CORS, TLS, forms, information disclosure. One GET per page and no payloads, limited to hosts the server allows. |
| **3. Unified report** | Test results, regressions since the previous run, flaky tests and security findings in one report, with screenshots, DOM snapshots and Playwright traces for every test. |
| **4. AI remediation** | Fix proposals a human approves, and fix patches against the app's own code (FastAPI, Flask, Django, Express, nginx), syntax-checked and opened as a GitHub pull request in one click. |
| **5. Validation engine** | Re-runs the original check after a fix; findings resolve or reopen as regressions. |
| **6. Verified deploy** | Calls the deploy hook (Render, Vercel, Netlify), waits for the new version to be healthy, runs smoke tests, and rolls back automatically if either fails. |

Around the loop: scheduled runs and GitHub push webhooks, commit statuses on GitHub, Slack alerts, JUnit XML
export, quarantine for known-bad tests, an audit trail of every action, sign-in with per-user data isolation,
and a dashboard that shows the loop live.

---

## Results

| Measurement | Result |
| --- | --- |
| **Self-healing benchmark** — 277 broken-locator cases (4 pages × every target × 15 mutations), [details](docs/healing-benchmark.md) | Heals **95.2%** of the cases where healing is right with **0 false heals**, and refuses **100%** of the cases where it is wrong. A static fallback chain heals 96.1% but **17.4%** of its heals hit the wrong element. |
| **Live sites** — the-internet.herokuapp.com, saucedemo.com, practicetestautomation.com, TodoMVC | 4 of 4 run the written goal (log in, add an item) and pass |
| **Real repositories** — FastAPI, Express and Django RealWorld apps, microblog, Flask | 5 of 5 get a fix patch that applies to a fresh clone and compiles |
| **Security and robustness** — SSRF, access control, input limits, webhook signatures, rate limits | 52 of 52 checks pass |
| **Load** — one API worker, [details](docs/load-test.md) | ~600–700 requests/s from 1 to 100 concurrent clients (p95 250 ms, no errors); 8 pipeline runs at once finish in 27 s at ~460 MB |
| **Accessibility** | WCAG 2.1 AA (axe) on every dashboard page, light and dark |
| **Automated tests** | 1,550+ backend, engine and end-to-end tests, plus frontend unit tests, in CI |

---

## Architecture

```
frontend/  React dashboard ──────────────▶ backend/  FastAPI
                                             │  api/            REST endpoints
                                             │  pipeline/       pipeline runner, scheduler, verified deploy
                                             │  orchestration/  ties the agents to the engine
                                             │  database/       Store interface: Firestore, local JSON, memory
                                             │  artifacts.py    screenshots, DOM snapshots, traces (disk or GCS)
                                             │  github.py, notify.py, netguard.py, http_hardening.py
                                             ▼
        agents/   planner, failure analyzer, healing decisions, memory, LLM client
        engine/   Playwright runner, locator healing, egress guard, benchmarks
        security/ passive scanner, remediation proposals, fix patcher
        ingestion/ repository blueprint
```

| Folder | Contents |
| --- | --- |
| [`agents/`](agents/) | Test Planner, Failure Analyzer, healing decision engine, healing memory, agent orchestrator and recovery policy, provider-independent LLM client (mock, local, OpenAI-compatible API) |
| [`engine/`](engine/) | Playwright execution engine, locator healer, outbound request guard for the browser, healing benchmarks |
| [`backend/`](backend/) | FastAPI API, automated pipeline and scheduler, verified deploy, artifact store, integrations (GitHub, Slack), sign-in and data isolation, request hardening |
| [`frontend/`](frontend/) | React dashboard with its design system, live pipeline loop, run pages, reports, security, profile and privacy pages |
| [`security/`](security/) | Passive security scanner, remediation proposals, fix patch generator |
| [`ingestion/`](ingestion/) | Repository cloning and static analysis |
| [`tests/`](tests/) | Unit, integration, engine and end-to-end tests |
| [`scripts/`](scripts/) | Load test |
| [`docs/`](docs/) | Architecture, operations and benchmark reports |

---

## Team

| Member | Area | Main folders | Branch |
| --- | --- | --- | --- |
| **Vinamra Bhatnagar** | Member 1 — AI agents & intelligence | `agents/` | [`vinamra-branch`](../../tree/vinamra-branch) |
| **Krishna Singh** | Member 2 — Browser engine, self-healing & security testing | `engine/`, `security/`, `ingestion/`, `scripts/` | [`krishna-branch`](../../tree/krishna-branch) |
| **Prashansha Maheshwari** | Member 3 — Platform backend, pipeline & dashboard | `backend/`, `frontend/`, `docs/` | [`prashansha-branch`](../../tree/prashansha-branch) |

Each member branch contains the full project; its README describes that member's part in detail.
Work is merged into `main` through pull requests that pass CI.

---

## Getting started

```bash
git clone https://github.com/Krishna201i/TestSphere-AI-Autonomous-Agentic-QA-Self-Healing-Testing-Platform.git
cd TestSphere-AI-Autonomous-Agentic-QA-Self-Healing-Testing-Platform

# Python package with development tools, and the browser
pip install -e ".[dev]"
python -m playwright install chromium

# Dashboard
cd frontend && npm install && cd ..

# Settings: works offline by default (LLM_PROVIDER=mock, local JSON database, sign-in off)
cp .env.example .env
```

Run the platform:

```bash
python -m uvicorn backend.main:app --port 8000   # API on http://127.0.0.1:8000
cd frontend && npm run dev                        # dashboard on http://localhost:3000
```

Run the tests:

```bash
python -m pytest -q                 # backend, agents, engine; end-to-end tests need: cd frontend && npm run build
cd frontend && npm test             # dashboard unit tests and design-token lint
```

Measure and scan:

```bash
python -m engine.heal_benchmark --quick    # self-healing benchmark (drop --quick for all 277 cases)
python scripts/loadtest.py                 # load test
python -m security http://127.0.0.1:8000/  # passive security scan (loopback is always in scope)
```

---

## Configuration and deployment

Production runs on Render with Firebase (Authentication and Firestore). The most important settings:

| Setting | Purpose |
| --- | --- |
| `FIREBASE_CREDENTIALS`, `FIREBASE_WEB_API_KEY`, `FIREBASE_AUTH_DOMAIN` | Database and sign-in |
| `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL` | AI model (`mock`, `local` such as Ollama, or any OpenAI-compatible `api`) |
| `SECURITY_SCAN_ALLOWED_HOSTS` | Hosts the passive scanner may contact (only hosts you own or may test) |
| `ARTIFACT_STORE=gcs`, `ARTIFACT_BUCKET` | Keep screenshots and traces in Cloud Storage |
| `TOKEN_ENCRYPTION_KEY` | Encrypts connected GitHub tokens (required when hosted) |
| `PIPELINE_EXECUTION=worker` | Run pipelines in a separate worker service |
| `DASHBOARD_URL` | Links in Slack alerts and GitHub commit statuses |

Every setting, the Dockerfile, the worker, Firestore rules and indexes, and CI are described in the
[Deployment & Operations Guide](docs/deployment-operations.md).

---

## Documentation

- [Backend architecture & API](docs/backend-architecture.md)
- [Browser execution engine](docs/engine-architecture.md)
- [Self-healing & orchestration](docs/self-healing-orchestration.md)
- [AI agent architecture](docs/member1-architecture.md)
- [Integration guide](docs/integration-guide.md)
- [Deployment & operations](docs/deployment-operations.md)
- [Healing benchmark](docs/healing-benchmark.md) · [Load test](docs/load-test.md)
- [Contributing](CONTRIBUTING.md)

## Security and privacy

- The scanner is passive and scope-limited; testing a site needs its owner's permission.
- Every outbound request, including everything the test browser loads, goes through an SSRF guard.
- Each user sees only their own data. The privacy notice in the dashboard explains what is stored, and
  *Delete account* erases it together with the sign-in account.

## License

[MIT](LICENSE)
