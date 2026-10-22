# TestSphere-AI Deployment, Operations & Configuration Guide

## 1. System Requirements & Environment

TestSphere-AI is designed to run in both local developer environments and containerized cloud setups (AWS ECS, GCP Cloud Run, Azure Container Apps, Kubernetes).

### Minimum Requirements:
- **Operating System**: Linux (Ubuntu 22.04+ recommended), macOS, or Windows 10/11
- **Python**: 3.11 or 3.12 (`pyproject.toml` requires >= 3.11)
- **Memory**: 4 GB RAM minimum (8 GB recommended when running headed Playwright browsers)
- **Disk Space**: 2 GB free disk space for browser binaries and test artifact storage

---

## 2. Environment Configuration Reference

All settings can be configured via environment variables or a `.env` file at repository root.

### 2.1 Backend & Database Settings
| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `DATABASE_BACKEND` | `firestore` if credentials set, else `local` | `firestore` (production), `local` (JSON file), `memory` (tests) |
| `FIREBASE_CREDENTIALS` | `""` | Service-account key JSON (whole file contents) or a path to it. A bare file name also resolves to a Render Secret File in `/etc/secrets/` |
| `FIREBASE_PROJECT_ID` | from the key | Firebase project id (optional) |
| `LOCAL_DB_PATH` | `./data/local_db.json` | Database file for `DATABASE_BACKEND=local` |
| `API_HOST` | `0.0.0.0` | Host binding interface for FastAPI |
| `API_PORT` | `8000` | Port for FastAPI server |
| `DEBUG` | `False` | Enable detailed stack traces and auto-reloading |
| `CORS_ORIGINS` | Vite dev servers (`localhost`/`127.0.0.1` on 3000 and 5173) locally; none when hosted | Comma-separated origins of a dashboard hosted elsewhere (e.g. `https://testsphere.vercel.app`). Not needed when the API serves the dashboard itself |

### 2.1a Sign-in & Automated Pipeline
| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `AUTH_REQUIRED` | `true` if Firebase credentials set, else `false` | Require Firebase sign-in for every API call; each user sees only their own data. `false` = single local user. On a hosted server (Render etc., or `APP_ENV` other than `development`) the backend **refuses to start** if sign-in is off only because credentials are missing; set `AUTH_REQUIRED=false` to run open on purpose |
| `FIREBASE_WEB_API_KEY` | `""` | Public web API key (Firebase console → Project settings → General → Your apps → Web app). Needed for the login page |
| `FIREBASE_AUTH_DOMAIN` | `<project id>.firebaseapp.com` | Auth domain for the login page (optional) |
| `SCHEDULER_ENABLED` | `true` | Run scheduled pipeline re-runs while the server is awake |
| `SCHEDULER_INTERVAL_SECONDS` | `60` | How often the scheduler checks for due projects |
| `CRON_SECRET` | `""` | Enables `POST /api/pipelines/scheduler/tick` (header `X-Cron-Secret`) so an external cron can wake a sleeping host and start due runs |

Firebase console setup for sign-in: **Authentication → Get started**, enable **Email/Password** (and **Google** if wanted)
under *Sign-in method*, and add the dashboard's domain under *Settings → Authorized domains*.
GitHub push webhooks are per project: the Automation page shows each project's payload URL and secret.

### 2.2 AI Agent Settings
| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `LLM_PROVIDER` | `mock` | `mock` (offline, deterministic) or `api` (any OpenAI-compatible chat API). `local` is reserved, not yet implemented |
| `LLM_API_KEY` | `""` | API key for the configured endpoint (required if `LLM_PROVIDER=api`) |
| `LLM_BASE_URL` | OpenAI | Base URL of the OpenAI-compatible endpoint (OpenAI, Anthropic, Gemini, Groq, OpenRouter) |
| `LLM_MODEL` | `mock-model` | Model identifier sent to the endpoint |
| `LLM_TEMPERATURE` | `0.2` | Sampling temperature for test synthesis and healing decisions |
| `LLM_MAX_TOKENS` | `4096` | Max output tokens per request |
| `LLM_TIMEOUT` | `60` | Request timeout in seconds |
| `LLM_MAX_RETRIES` | `2` | Retries for transient errors (timeouts, 429, 5xx, network) |
| `AGENT_MEMORY_BACKEND` | `database` | `database` persists healing memory in the configured store (survives restarts); `memory` keeps it in-process |
| `INGEST_WORKSPACE` | `./data/repos` | Where ingested repositories are cloned |
| `INGEST_GIT_HOSTS` | `github.com,gitlab.com,bitbucket.org` | Hosts public repositories may be cloned from (https only) |
| `INGEST_ALLOW_LOCAL_PATHS` | `true` locally in development; `false` on Render/Heroku/Railway/Fly/Cloud Run unless set | Accept local folder paths for ingestion (reads the server's disk); never enable on a public server |
| `SECURITY_SCAN_ALLOWED_HOSTS` | `""` | Extra hosts the passive scanner may contact (loopback always allowed) |
| `RATE_LIMIT_RUNS_PER_MINUTE` | `10` | Runs, scans and clones each user may start per minute (`0` disables); over it the API answers 429 |
| `ENGINE_MAX_BROWSERS` | `2` | Chromium instances that may run at once; further runs wait for a slot |
| `LOG_LEVEL` | `INFO` | Level for the app's own loggers |
| `LOG_FORMAT` | `json` when hosted, `text` locally | `json` = one JSON object per line (ts, level, logger, message, request_id, extras), searchable in Render's log viewer |
| `SENTRY_DSN` | `""` | Send unhandled errors to Sentry (free tier is enough); no personal data or performance tracing is sent |

### 2.3 Browser Engine Settings
| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `BROWSER_TYPE` | `chromium` | Target browser engine: `chromium`, `firefox`, `webkit` |
| `HEADLESS` | `True` | Run browser in headless mode without visible window |
| `BROWSER_TIMEOUT_MS`| `10000` | Default element locator wait timeout in milliseconds |
| `CAPTURE_SCREENSHOTS`| `True` | Whether to capture PNG screenshots on step completion/failure |
| `CAPTURE_DOM_SNAPSHOT`| `True`| Whether to serialize DOM snapshot upon failure for healing |
| `ARTIFACTS_DIR` | `./artifacts` | Local directory path where run artifacts are stored |

---

## 2.4 Firestore rules and indexes

`firestore.rules` denies all client access (only the backend's Admin SDK, which bypasses rules, uses the
database). `firestore.indexes.json` lists the composite indexes for "newest N of my …" queries (test
executions, pipeline runs, audit events, blueprints). Deploy both with the Firebase CLI:

```bash
npm install -g firebase-tools && firebase login
firebase deploy --only firestore --project <your-project-id>
```

Without the indexes everything still works: the backend reads every matching document and sorts them
itself, and logs a one-time warning with a link that creates the missing index.

---

## 3. Docker Containerization

The repository's [`Dockerfile`](../Dockerfile) builds one image with the API,
the dashboard and headless Chromium:

- **Stage 1** (`node:24-slim`): `npm ci` and `npm run build` for the dashboard.
- **Stage 2** (`python:3.11-slim`): the hash-checked lock (`pip install --require-hashes -r requirements.txt`),
  Chromium with its system libraries (`playwright install --with-deps chromium`), the backend packages and
  the built dashboard. Runs as an unprivileged user (uid 10001) with a `HEALTHCHECK` on `/api/health`.

```bash
docker build -t testsphere .

# Production-like: Firebase sign-in and Firestore
docker run -p 8000:8000 --env-file .env testsphere

# Offline try-out without sign-in (the image sets APP_ENV=production, so
# running open has to be chosen explicitly)
docker run -p 8000:8000 -e AUTH_REQUIRED=false -e DATABASE_BACKEND=local testsphere
```

`PORT` (default 8000) sets the listening port. The image does not include `tests/` or `docs/`.

---

## 4. Continuous Integration

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs on every pull request and on pushes to `main`:

| Job | Steps |
|---|---|
| Backend | Install the lock with `--require-hashes`, install Chromium, `ruff check` (rules in `pyproject.toml`), the full pytest suite, `pip-audit` |
| Frontend | `npm ci`, `npm run build`, `npm audit --omit=dev --audit-level=high` |

Make both jobs required checks on `main` (GitHub → Settings → Branches → branch protection rule) so
nothing reaches Render without passing them.

---

## 5. Production Observability & Logging

- **Structured JSON Logging**: one JSON object per line by default when hosted (`LOG_FORMAT=json|text` overrides), with a `request_id` on every line written while handling a request; works with Render's log search, Datadog, CloudWatch or Grafana Loki.
- **Request ids**: every response carries `X-Request-ID`; send one in to correlate with your own logs.
- **Error tracking**: set `SENTRY_DSN` to report unhandled errors to Sentry.
- **Health Checks**: `GET /api/health` (public) reports database connectivity; signed-in users see browser availability in `GET /api/system`.
