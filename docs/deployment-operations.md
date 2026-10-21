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
| `FIREBASE_CREDENTIALS` | `""` | Service-account key JSON (whole file contents) or a path to it |
| `FIREBASE_PROJECT_ID` | from the key | Firebase project id (optional) |
| `LOCAL_DB_PATH` | `./data/local_db.json` | Database file for `DATABASE_BACKEND=local` |
| `API_HOST` | `0.0.0.0` | Host binding interface for FastAPI |
| `API_PORT` | `8000` | Port for FastAPI server |
| `DEBUG` | `False` | Enable detailed stack traces and auto-reloading |
| `CORS_ORIGINS` | `*` | Comma-separated list of allowed frontend origins |

### 2.1a Sign-in & Automated Pipeline
| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `AUTH_REQUIRED` | `true` if Firebase credentials set, else `false` | Require Firebase sign-in for every API call; each user sees only their own data. `false` = single local user |
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

## 3. Docker Containerization

> Example configuration. No `Dockerfile` or `docker-compose.yml` is committed yet; the live deployment uses Render (backend) and Vercel (frontend).

### 3.1 Dockerfile
```dockerfile
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browser engines
RUN playwright install chromium firefox webkit --with-deps

# Copy application source
COPY . .

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 3.2 Docker Compose (`docker-compose.yml`)
```yaml
version: '3.8'

services:
  testsphere-api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - FIREBASE_CREDENTIALS=${FIREBASE_CREDENTIALS}
      - LLM_PROVIDER=mock
      - HEADLESS=True
    volumes:
      - ./artifacts:/app/artifacts

```

---

## 4. Continuous Integration (CI/CD) Workflow

Example GitHub Actions workflow (not yet committed under `.github/workflows/`) running the full offline test suite (1,246 tests) across Python 3.11 and 3.12:

```yaml
name: TestSphere-AI CI

on:
  push:
    branches: [ main, develop, prashansha-branch ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]

    steps:
    - uses: actions/checkout@v4

    - name: Set up Python ${{ matrix.python-version }}
      uses: actions/setup-python@v5
      with:
        python-version: ${{ matrix.python-version }}

    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -e ".[dev]"
        playwright install chromium --with-deps

    - name: Run Test Suite
      env:
        LLM_PROVIDER: mock
      run: |
        python -m pytest tests/engine/ tests/backend/ tests/test_*.py -v
```

---

## 5. Production Observability & Logging

- **Structured JSON Logging**: Set `LOG_FORMAT=json` for compatibility with Datadog, CloudWatch, or Grafana Loki.
- **Health Checks**: Endpoint `GET /api/health` returns readiness probe status including database connectivity and browser binary availability.
