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

Write your own tests in plain English in **Test Studio** (or import your Playwright tests), review every heal on
the **Self-Healing** page, and let the AI agents run on a fallback chain of models (NVIDIA Gemma, Nemotron, Groq,
Gemini). How each part of the title is delivered: [platform overview](docs/platform-overview.md).

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
| **1. Codebase ingestion** | Clones a public repository (or reads a local folder in development) and builds a blueprint: languages, frameworks, dependencies, existing test suites, HTTP routes, committed secrets and debug flags, and reads its Playwright tests, which every run then replays as saved tests. Nothing in the repository is executed on the server. |
| **2A. AI QA agent** | Analyzes the live page (rendering JavaScript apps in a real browser), turns the written goal into steps using the values it contains, plans smoke, scenario, content and linked-page tests, and runs them in Playwright. With a real model, an AI explorer reaches the goal in a live browser once (opening menus, following tabs, never deleting or paying), verifies the outcome, and records the steps as a test that later runs replay without the model. A per-project generation profile chooses the kinds of tests (smoke, functional, negative, content, linked pages), the test data to type, how many AI-written tests to add and whether to leave out render-only tests; each form the browser validates gets negative tests (empty required fields, a malformed email). Every new test is then run once on a deliberately broken copy of its page, with what it checks removed: one that still passes is marked as checking nothing, so coverage is never overstated. |
| **Test Studio** | Write a test in plain English ("log in as demo / secret, add the backpack to the cart, check the cart shows 1"). The AI model (Groq or any OpenAI-compatible provider; the rule-based planner without one) turns it into steps from a fixed vocabulary, and every step is checked against the live page before anything runs: on the page, found by its text at run time, or not seen (the test is then saved quarantined until you trust it). You review and edit the steps, save the test, run it, or export it as a Playwright `.spec.ts`. Saved tests run in every pipeline run and self-heal like the rest. |
| **Repository tests** | Every run also reports the repository's own unit tests: the results of its CI on the run's commit (GitHub), or, without CI, a run in a sandbox (pytest, npm/yarn/pnpm test, go test) of throwaway containers capped in memory and CPU, with no network while testing and no access to the server or its secrets. Failing tests fail the run. |
| **Self-healing** | When a locator breaks, the engine tries stored fallbacks, then a fingerprint scan of the live DOM, scoring attributes, text, position and structure. It refuses look-alikes and elements whose kind changed. |
| **2B. Attacker agent** | Scope-checked security scan, limited to hosts the server allows. Passive by default (headers, cookies, CORS, TLS, forms, information disclosure — one GET per page, no payloads); optional active (DAST) mode sends reflected-XSS, SQL-injection and open-redirect probes to apps you own, and confirms each reflected XSS by running its payload in a real browser (unconfirmed reflections are marked as such, not reported as proven). With a real model, AI triage then prioritizes the findings, explains the real-world risk and drafts a fix — reasoning only over findings already produced in scope, never contacting the target itself. |
| **3. Unified report** | Test results, regressions since the previous run, flaky tests and security findings in one report, with screenshots, DOM snapshots and Playwright traces for every test. Every failure says why it happened and what to do next (from the failure analyzer), every run opens with a plain-language summary, and each run downloads as a PDF report (summary, failures with screenshots, all tests) or is shared through a read-only link that expires. |
| **4. AI remediation** | Every run turns the open findings into a fix patch against the app's own code (FastAPI, Flask, Django, Express, Next.js, nginx), syntax-checked, and shows it on the run page as *Fixes ready for review*. When the repository's own tests fail, the AI model proposes a change to the code (never to a test) and the tests run again in the sandbox with it: only a fix that makes every test pass is shown, as *AI fix for failing tests*. Approving either opens a pull request on GitHub or Bitbucket, or a merge request on GitLab; nothing changes in the repository until then. |
| **5. Validation engine** | Re-runs the original check after a fix; findings resolve or reopen as regressions. |
| **6. Verified deploy** | Calls the deploy hook (Render, Vercel, Netlify, or a GitHub Actions workflow for any other host), waits for the new version to be healthy, runs smoke tests, and rolls back automatically if either fails. |

Around the loop: scheduled runs and GitHub push webhooks, commit statuses on GitHub, Slack alerts, JUnit XML
export, quarantine for known-bad tests, an audit trail of every action, sign-in with per-user data isolation,
and a dashboard that shows the loop live.

---

## Results

| Measurement | Result |
| --- | --- |
| **Self-healing benchmark** — 277 broken-locator cases (4 pages × every target × 15 mutations), [details](docs/healing-benchmark.md) | Heals **95.7%** of the cases where healing is right with **0 false heals**, and refuses **100%** of the cases where it is wrong. A static fallback chain heals 96.1% but **17.4%** of its heals hit the wrong element. |
| **Plain-English tests** (Test Studio) — 15 instructions a tester would type, 19 real bugs, [details](docs/studio-eval.md) | **18 of 19** bugs caught with **0 false alarms** (rule-based planner, no AI model); 6 of 7 on held-out instructions it was never tuned on |
| **Live sites** — the-internet.herokuapp.com, saucedemo.com, practicetestautomation.com, TodoMVC | 4 of 4 run the written goal (log in, add an item) and pass |
| **Real repositories** — FastAPI, Express and Django RealWorld apps, microblog, Flask | 5 of 5 get a fix patch that applies to a fresh clone and compiles |
| **Security and robustness** — SSRF, access control, input limits, webhook signatures, rate limits | 52 of 52 checks pass |
| **Load** — one API worker, [details](docs/load-test.md) | ~600–700 requests/s from 1 to 100 concurrent clients (p95 250 ms, no errors); 8 pipeline runs at once finish in 27 s at ~460 MB |
| **Accessibility** | WCAG 2.1 AA (axe) on every dashboard page, light and dark |
| **Automated tests** | 2,000+ backend, engine and end-to-end tests and 95 frontend unit tests, in CI; the healing and Test Studio benchmarks gate every change (any false heal or false alarm fails the build), and the AI layer is covered end to end: no false heal through the AI healer, no harm from a page's injected instructions |

---

## Architecture

```
frontend/  React dashboard ──────────────▶ backend/app/  FastAPI
                                             │  api/            REST endpoints
                                             │  pipeline/       pipeline runner, scheduler, verified deploy
                                             │  orchestration/  ties the agents to the engine
                                             │  database/       Store interface: Firestore, local JSON, memory
                                             │  artifacts.py    screenshots, DOM snapshots, traces (disk, S3 or GCS)
                                             │  github.py, notify.py, netguard.py, http_hardening.py
                                             ▼
        backend/agents/     planner, failure analyzer, healing decisions, memory, LLM client
        backend/engine/     Playwright runner, locator healing, egress guard, benchmarks
        backend/security/   passive + active (DAST) scanner, remediation, fix patcher
        backend/ingestion/  repository blueprint
```

The repository has three parts: **`backend/`** (all Python: `pyproject.toml`, the dependency lock and tests live
there, and every Python command runs from it), **`frontend/`** (the dashboard) and **`docs/`**. Each of `backend/` and `frontend/` has
its own `Dockerfile` (two containers); [`docker-compose.yml`](docker-compose.yml), [`deploy/aws-ec2`](deploy/aws-ec2/README.md) and the
Firestore rules stay at the root.

| Folder | Contents |
| --- | --- |
| [`backend/app/`](backend/app/) | FastAPI API, automated pipeline and scheduler, pipeline worker, verified deploy, artifact store, integrations (GitHub, Slack), sign-in and data isolation, request hardening, MCP server |
| [`backend/agents/`](backend/agents/) | Test Planner, Failure Analyzer, healing decision engine, healing memory, agent orchestrator and recovery policy, provider-independent LLM client (mock, local, OpenAI-compatible API) |
| [`backend/engine/`](backend/engine/) | Playwright execution engine, locator healer, outbound request guard for the browser, healing benchmarks |
| [`backend/security/`](backend/security/) | Passive and active security scanner, remediation proposals, fix patch generator |
| [`backend/ingestion/`](backend/ingestion/) | Repository cloning and static analysis |
| [`backend/tests/`](backend/tests/) | Unit, integration, engine and end-to-end tests |
| [`backend/scripts/`](backend/scripts/) | Load test, test-generation evaluation |
| [`frontend/`](frontend/) | React dashboard with its design system, live pipeline loop, run pages, reports, security, profile and privacy pages |
| [`docs/`](docs/) | Architecture, operations, contributing guide and benchmark reports |

---

## Team

| Member | Area | Main folders | Branch |
| --- | --- | --- | --- |
| **Vinamra Bhatnagar** | Member 1 — AI agents & intelligence | `agents/` | [`vinamra-branch`](../../tree/vinamra-branch) |
| **Krishna Singh** | Member 2 — Browser engine, self-healing & security testing | `engine/`, `security/`, `ingestion/`, `scripts/` | [`krishna-branch`](../../tree/krishna-branch) |
| **Prashansha Maheshwari** | Member 3 — Platform backend, pipeline & dashboard | `backend/`, `frontend/`, `docs/` | [`prashansha-branch`](../../tree/prashansha-branch) |

Each member branch contains the full project; its README describes that member's part in detail.
Work is merged into `main` through pull requests that pass CI.

### Contributions

| Member | Contributed |
| --- | --- |
| **Vinamra Bhatnagar** | Founded the AI agent layer: the shared agent schemas and contracts, the provider-independent LLM client (mock provider, response parser, `LLMClientSession` with validation and retry), the Test Planner Agent (schemas, prompt architecture, mock scenarios, generation pipeline), the failure classifier and Failure Analysis Agent, the self-healing contracts, test prioritization, their tests. |
| **Krishna Singh** | The Playwright engine and locator healing with its benchmark, the passive and active security scanner and AI triage, codebase ingestion, fix patches and pull requests, verified deploy, the real LLM providers, persistent healing memory, the AI explorer, failure reports and PDF export, Firestore storage, CI and security scanning, hosting, and most of the current backend and dashboard. |
| **Prashansha Maheshwari** | The first backend platform and workflow orchestration, the plan-and-execute API with live SSE events, the first React dashboard and its connection to the backend, the Vercel and Render deployment setup, the two-container Docker setup (frontend on nginx, backend) with its CI smoke tests and continuous deployment to AWS, and the architecture, API, engine, integration and operations documentation, plus [`CONTRIBUTING.md`](docs/CONTRIBUTING.md). |

---

## Getting started

```bash
git clone https://github.com/Krishna201i/TestSphere-AI-Autonomous-Agentic-QA-Self-Healing-Testing-Platform.git
cd TestSphere-AI-Autonomous-Agentic-QA-Self-Healing-Testing-Platform

# Python package with development tools, and the browser (all Python lives in backend/)
cd backend
pip install -r requirements.txt && pip install -e ".[dev]"
python -m playwright install chromium
cd ..

# Dashboard
cd frontend && npm install && cd ..

# Settings: works offline by default (LLM_PROVIDER=mock, local JSON database, sign-in off)
cp .env.example .env
```

Run the platform:

```bash
cd backend && python -m uvicorn app.main:app --port 8000   # API on http://127.0.0.1:8000
cd frontend && npm run dev                                 # dashboard (second terminal) on http://localhost:3000
```

Or in Docker, as two containers (dashboard on nginx, backend with Chromium):

```bash
docker compose up --build   # http://localhost:8080
```

Run the tests:

```bash
cd backend && python -m pytest -q   # app, agents, engine; end-to-end tests need: cd frontend && npm run build
cd frontend && npm test             # dashboard unit tests and design-token lint
```

Measure and scan (from `backend/`):

```bash
python -m engine.heal_benchmark --quick    # self-healing benchmark (drop --quick for all 277 cases)
python scripts/loadtest.py                 # load test
python -m security http://127.0.0.1:8000/           # passive scan (loopback is always in scope)
python -m security http://127.0.0.1:8000/?q=x --active  # also send DAST probes (apps you own only)
```

---

## Configuration and deployment

Production runs on one AWS EC2 instance (API with the dashboard, a pipeline worker and Caddy for HTTPS; see
[`deploy/aws-ec2`](deploy/aws-ec2/README.md)) with Firebase (Authentication and Firestore). The most important settings:

| Setting | Purpose |
| --- | --- |
| `FIREBASE_CREDENTIALS`, `FIREBASE_WEB_API_KEY`, `FIREBASE_AUTH_DOMAIN` | Database and sign-in |
| `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL` | AI model (`mock`, `local` such as Ollama, or any OpenAI-compatible `api`) |
| `LLM_PROVIDER=chain`, `NVIDIA_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY` | Fallback chain: NVIDIA Gemma → NVIDIA Nemotron → Groq → Gemini. A provider that hits its rate limit or quota is left out until it resets, so the rest of the work continues on the next one; `python -m agents.llm.check` tests every provider |
| `SECURITY_SCAN_ALLOWED_HOSTS` | Hosts the scanner may contact (only hosts you own or may test) |
| `SECURITY_ACTIVE_SCAN` | Allow active (DAST) scanning — XSS, SQLi and open-redirect probes; off by default, authorized hosts only |
| `REQUIRE_DOMAIN_VERIFICATION` | Active scans need proof the account owns the host: a project's token published at `/.well-known/testsphere-verify.txt` (`POST /api/projects/{id}/domain-verification`), valid 30 days; `auto` (default) = on for a hosted server with sign-in, or `on` / `off` |
| `ARTIFACT_STORE=s3` (or `gcs`), `ARTIFACT_BUCKET` | Keep screenshots and traces in an S3 (or Cloud Storage) bucket |
| `TOKEN_ENCRYPTION_KEY` | Encrypts connected GitHub tokens (required when hosted) |
| `PIPELINE_EXECUTION=worker` | Run pipelines in a separate worker service |
| `DASHBOARD_URL` | Links in Slack alerts and GitHub commit statuses |

Every setting, the two Docker images, the worker, Firestore rules and indexes, and CI are described in the
[Deployment & Operations Guide](docs/deployment-operations.md).

---

## Documentation

- [Platform overview](docs/platform-overview.md): the five pillars, architecture diagram and results
- [Demo script](docs/demo-script.md): a 10-minute walkthrough
- [Backend architecture & API](docs/backend-architecture.md)
- [Browser execution engine](docs/engine-architecture.md)
- [Self-healing & orchestration](docs/self-healing-orchestration.md)
- [Integration guide](docs/integration-guide.md)
- [MCP server for coding agents](docs/mcp-server.md)
- [Deployment & operations](docs/deployment-operations.md)
- [Healing benchmark](docs/healing-benchmark.md) · [Test Studio benchmark](docs/studio-eval.md) · [Load test](docs/load-test.md)
- [Contributing](docs/CONTRIBUTING.md)

## Security and privacy

- Scanning is scope-limited to an allowlist; testing a site needs its owner's permission. The scanner is passive by default, with opt-in active (DAST) probes behind a server switch.
- Every outbound request, including everything the test browser loads, goes through an SSRF guard that resolves
  each host once, refuses internal addresses and connects only to the address it checked (no DNS rebinding).
- Text from the site under test reaches the AI only as fenced, untrusted data, and every action the AI proposes is checked in code (guardrails, selector whitelist, the engine's heal checks, scan scope), so a page that tries to instruct the AI cannot make a run click, type or navigate somewhere harmful.
- Each user sees only their own data. The privacy notice in the dashboard explains what is stored, and
  *Delete account* erases it together with the sign-in account.

## License

[MIT](LICENSE)
