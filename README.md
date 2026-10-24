# TestSphere AI — Member 3: Platform Backend, Pipeline & Dashboard

**Owner:** Prashansha Maheshwari · **Branch:** `prashansha-branch` · **Main folders:** [`backend/`](backend/),
[`frontend/`](frontend/), [`docs/`](docs/)

This branch contains the whole TestSphere AI project. This README covers the part Member 3 owns: the FastAPI
backend, the automated pipeline and verified deploy, the integrations and the React dashboard. For the overview
of the whole platform, see the [README on `main`](../../tree/main#readme).

---

## What this part does

- **API.** FastAPI endpoints for projects, test cases, executions, pipeline runs, security findings, fix
  patches, deployments, integrations, audit, the account and privacy.
- **Automated pipeline.** Runs the loop stage by stage (codebase, analyze, plan, execute, heal, security,
  report). Runs start by hand, on a schedule, or from a GitHub push webhook. A separate worker service can run
  them.
- **Verified deploy.** Calls the deploy hook (Render, Vercel, Netlify), waits for the new version to be healthy,
  runs smoke tests and rolls back automatically if either fails.
- **Integrations.** GitHub: pull requests from fix patches and commit statuses on pushed runs, with tokens
  encrypted at rest. Also Slack alerts and JUnit XML export.
- **Storage.** One Store interface over Firestore, local JSON and memory. Artifacts are kept on disk or in
  Google Cloud Storage.
- **Safety.** Firebase sign-in with per-user data isolation, an SSRF guard on every outbound request, rate
  limits, security headers, body size limits and an audit trail.
- **Dashboard.** A React app with its own design system, light and dark themes, the live pipeline loop, run
  details with traces, reports, security, remediation, validation, deployments, profile and privacy.

## Modules

| Module | Contents |
| --- | --- |
| [`backend/api/`](backend/api/) | REST endpoints |
| [`backend/pipeline/`](backend/pipeline/) | Pipeline runner, scheduler, suites, verified deploy and its configuration |
| [`backend/orchestration/`](backend/orchestration/) | Connects the agents (Member 1) with the engine (Member 2) |
| [`backend/services/`](backend/services/) | Projects, test cases, executions, security, URL analysis |
| [`backend/database/`](backend/database/) | Store interface and implementations |
| [`backend/github.py`](backend/github.py), [`backend/notify.py`](backend/notify.py), [`backend/secretbox.py`](backend/secretbox.py) | GitHub, Slack, token encryption |
| [`backend/netguard.py`](backend/netguard.py), [`backend/http_hardening.py`](backend/http_hardening.py), [`backend/ratelimit.py`](backend/ratelimit.py), [`backend/auth.py`](backend/auth.py) | SSRF guard, request hardening, rate limits, sign-in |
| [`backend/worker.py`](backend/worker.py) | Pipeline worker service |
| [`frontend/src/pages/`](frontend/src/pages/), [`frontend/src/components/`](frontend/src/components/) | Dashboard pages and components |
| [`frontend/src/styles/`](frontend/src/styles/) | Design system tokens and theme |
| [`docs/`](docs/) | Architecture, integration and operations guides |

## Results this part contributes

- **Security and robustness:** 52 of 52 checks pass (SSRF, access control, input limits, webhook signatures,
  rate limits).
- **Accessibility:** WCAG 2.1 AA (axe) on every dashboard page, light and dark, checked in CI.
- **Load:** ~600–700 requests/s on one API worker from 1 to 100 concurrent clients, p95 250 ms, no errors
  ([report](docs/load-test.md)).

## Working on this part

```bash
pip install -e ".[dev]"
python -m playwright install chromium
cd frontend && npm install && cd ..
cp .env.example .env

python -m uvicorn backend.main:app --port 8000   # API
cd frontend && npm run dev                        # dashboard on http://localhost:3000

python -m pytest tests/backend -q                 # backend tests
cd frontend && npm run build && cd .. && python -m pytest tests/e2e -q   # dashboard end-to-end and accessibility
cd frontend && npm test                           # frontend unit tests and design-token lint
```

Documentation: [Backend architecture & API](docs/backend-architecture.md) ·
[Deployment & operations](docs/deployment-operations.md) · [Integration guide](docs/integration-guide.md)

## How work reaches `main`

1. Branch from `prashansha-branch` or work on it directly.
2. Keep the backend, end-to-end and frontend tests passing; dashboard colours come from the design tokens.
3. Open a pull request into `main`. CI runs the full test suite, the security scans and the frontend build.
