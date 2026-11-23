# TestSphere AI — Autonomous Agentic QA & Self-Healing Testing Platform

An end-to-end, multi-agent platform for web application testing: an AI QA agent plans and runs smoke,
functional and negative tests in a real browser, an engine self-heals broken locators without false heals, an
attacker agent scans for security vulnerabilities and drafts code patches, and results feed into unified
reports, flaky-test tracking and verified deployment with automatic rollback.

Built for the GLA University capstone project (Group 24, B.Tech CSE AIML 2022–2026).

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
there, and every Python command runs from it), **`frontend/`** (the dashboard) and **`docs/`**. Deployment files
(`Dockerfile`, [`deploy/aws-ec2`](deploy/aws-ec2/README.md), Firestore rules) stay at the root.

| Folder | Contents |
| --- | --- |
| [`backend/app/`](backend/app/) | FastAPI API, automated pipeline and scheduler, pipeline worker, verified deploy, artifact store, integrations (GitHub, Slack), sign-in and data isolation, request hardening, MCP server |
| [`backend/agents/`](backend/agents/) | Test Planner, Failure Analyzer, healing decision engine, healing memory, agent orchestrator and recovery policy, provider-independent LLM client (mock, local, OpenAI-compatible API) |
| [`backend/engine/`](backend/engine/) | Playwright execution engine, locator healer, outbound request guard for the browser, healing benchmarks |
| [`backend/security/`](backend/security/) | Passive and active security scanner, remediation proposals, fix patch generator, SARIF v2.1.0 exporter |
| [`backend/ingestion/`](backend/ingestion/) | Repository cloning and static analysis |
| [`backend/tests/`](backend/tests/) | Unit, integration, engine and end-to-end tests |
| [`backend/scripts/`](backend/scripts/) | Load test, test-generation evaluation, demo runner |
| [`frontend/`](frontend/) | React dashboard with its design system, live pipeline loop, run pages, reports, security, profile and privacy pages |
| [`docs/`](docs/) | Architecture, operations, contributing guide and benchmark reports |

---

## Results & Verified Capabilities

| Capability | Verified Performance / Metric |
| --- | --- |
| **Self-healing benchmark** — 277 broken-locator cases (4 pages × every target × 15 mutations), [details](docs/healing-benchmark.md) | Heals **95.7%** of the cases where healing is right with **0 false heals**, and refuses **100%** of the cases where it is wrong. A static fallback chain heals 96.1% but **17.4%** of its heals hit the wrong element. |
| **Plain-English tests** (Test Studio) — 15 instructions a tester would type, 19 real bugs, [details](docs/studio-eval.md) | **18 of 19** bugs caught with **0 false alarms** (rule-based planner, no AI model); 6 of 7 on held-out instructions it was never tuned on |
| **Live sites** — the-internet.herokuapp.com, saucedemo.com, practicetestautomation.com, TodoMVC | 4 of 4 run the written goal (log in, add an item) and pass |
| **Real repositories** — FastAPI, Express and Django RealWorld apps, microblog, Flask | 5 of 5 get a fix patch that applies to a fresh clone and compiles |
| **Security and robustness** — SSRF, access control, input limits, webhook signatures, rate limits, SARIF v2.1.0 export | 55 of 55 checks pass |
| **Load** — one API worker, [details](docs/load-test.md) | ~600–700 requests/s from 1 to 100 concurrent clients (p95 250 ms, no errors); 8 pipeline runs at once finish in 27 s at ~460 MB |
| **Accessibility** | WCAG 2.1 AA (axe) on every dashboard page, light and dark |
| **Automated tests** | 2,000+ backend, engine and end-to-end tests and 95 frontend unit tests, in CI; the healing and Test Studio benchmarks gate every change |

---

## Team

| Member | Area | Main folders | Branch |
| --- | --- | --- | --- |
| **Vinamra Bhatnagar** | Member 1 — AI agents & intelligence | `backend/agents/`, `backend/security/` | [`vinamra-branch`](../../tree/vinamra-branch) |
| **Krishna Singh** | Member 2 — Browser engine, self-healing & security testing | `backend/engine/`, `backend/security/`, `backend/ingestion/` | [`krishna-branch`](../../tree/krishna-branch) |
| **Prashansha Maheshwari** | Member 3 — Platform backend, pipeline & dashboard | `backend/app/`, `frontend/`, `docs/` | [`prashansha-branch`](../../tree/prashansha-branch) |

Each member branch contains the full project; its README describes that member's part in detail.
Work is merged into `main` through pull requests that pass CI.

### Contributions

| Member | Contributed |
| --- | --- |
| **Vinamra Bhatnagar** | Founded the AI agent layer: the shared agent schemas and contracts, the provider-independent LLM client (mock provider, response parser, `LLMClientSession` with validation and retry), the Test Planner Agent (schemas, prompt architecture, mock scenarios, generation pipeline, risk-based prioritization), the failure classifier and Failure Analysis Agent (deterministic failure grouping and shared root-cause clustering), multi-tenant memory read isolation, self-healing false-heal safeguards, explainable flaky-test detection, SARIF v2.1.0 standard exporter, PEP 503 dependency patch matching, and agent observability execution timeline. |
| **Krishna Singh** | The Playwright engine and locator healing with its benchmark, the passive and active security scanner and AI triage, codebase ingestion, fix patches and pull requests, verified deploy, the real LLM providers, persistent healing memory, the AI explorer, failure reports and PDF export, Firestore storage, CI and security scanning, hosting, and most of the current backend and dashboard. |
| **Prashansha Maheshwari** | The first backend platform and workflow orchestration, the plan-and-execute API with live SSE events, the first React dashboard and its connection to the backend, the Vercel and Render deployment setup, and the architecture, API, engine, integration and operations documentation, plus [`CONTRIBUTING.md`](docs/CONTRIBUTING.md). |

---

## Getting Started

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

Start the servers:
```bash
cd backend && python -m uvicorn app.main:app --port 8000   # API on http://127.0.0.1:8000
cd frontend && npm run dev                                 # dashboard (second terminal) on http://localhost:3000
```

Run tests:
```bash
cd backend && python -m pytest -q   # app, agents, engine; end-to-end tests need: cd frontend && npm run build
cd frontend && npm test             # dashboard unit tests and design-token lint
```

Run the end-to-end demo loop:
```bash
make demo
```

---

## Configuration and Deployment

Production runs on one AWS EC2 instance with Firebase (Authentication and Firestore). Key settings:

| Setting | Purpose |
| --- | --- |
| `FIREBASE_CREDENTIALS`, `FIREBASE_WEB_API_KEY`, `FIREBASE_AUTH_DOMAIN` | Database and sign-in |
| `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL` | AI model (`mock`, `local` such as Ollama, or any OpenAI-compatible `api`) |
| `LLM_PROVIDER=chain`, `NVIDIA_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY` | Fallback chain: NVIDIA Gemma → NVIDIA Nemotron → Groq → Gemini |
| `SECURITY_SCAN_ALLOWED_HOSTS` | Hosts the scanner may contact |
| `SECURITY_ACTIVE_SCAN` | Allow active (DAST) scanning |

---

## License

[MIT](LICENSE)
