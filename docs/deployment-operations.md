# TestSphere-AI Deployment, Operations & Configuration Guide

## 1. System Requirements & Environment

TestSphere-AI is designed to run in both local developer environments and containerized cloud setups (AWS ECS, GCP Cloud Run, Azure Container Apps, Kubernetes).

### Minimum Requirements:
- **Operating System**: Linux (Ubuntu 22.04+ recommended), macOS, or Windows 10/11
- **Python**: 3.10, 3.11, or 3.12
- **Memory**: 4 GB RAM minimum (8 GB recommended when running headed Playwright browsers)
- **Disk Space**: 2 GB free disk space for browser binaries and test artifact storage

---

## 2. Environment Configuration Reference

All settings can be configured via environment variables or a `.env` file at repository root.

### 2.1 Backend & Database Settings
| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `DATABASE_URL` | `sqlite:///./testsphere.db` | Relational database connection string (SQLite or PostgreSQL) |
| `API_HOST` | `0.0.0.0` | Host binding interface for FastAPI |
| `API_PORT` | `8000` | Port for FastAPI server |
| `DEBUG` | `False` | Enable detailed stack traces and auto-reloading |
| `CORS_ORIGINS` | `*` | Comma-separated list of allowed frontend origins |

### 2.2 AI Agent Settings
| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `LLM_PROVIDER` | `mock` | LLM provider: `mock`, `openai`, `anthropic`, `gemini` |
| `OPENAI_API_KEY` | `""` | OpenAI API key (required if `LLM_PROVIDER=openai`) |
| `ANTHROPIC_API_KEY` | `""` | Anthropic API key (required if `LLM_PROVIDER=anthropic`) |
| `GEMINI_API_KEY` | `""` | Google Gemini API key (required if `LLM_PROVIDER=gemini`) |
| `LLM_MODEL` | `gpt-4o` | LLM model identifier |
| `LLM_TEMPERATURE` | `0.1` | Sampling temperature for test synthesis and healing decisions |
| `LLM_MAX_RETRIES` | `3` | Maximum LLM client retry attempts before error escalation |

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
  db:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: testsphere
      POSTGRES_USER: testsphere_user
      POSTGRES_PASSWORD: testsphere_secret
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

  testsphere-api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://testsphere_user:testsphere_secret@db:5432/testsphere
      - LLM_PROVIDER=mock
      - HEADLESS=True
    depends_on:
      - db
    volumes:
      - ./artifacts:/app/artifacts

volumes:
  pgdata:
```

---

## 4. Continuous Integration (CI/CD) Workflow

Example GitHub Actions workflow running all 1,102 automated tests across Python 3.10, 3.11, and 3.12:

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
        python-version: ["3.10", "3.11", "3.12"]

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
