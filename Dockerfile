# TestSphere-AI: API + dashboard + headless Chromium in one image.
#   docker build -t testsphere .
#   docker run -p 8000:8000 --env-file .env testsphere

# ---- Dashboard build ---------------------------------------------------------
FROM node:24-slim AS dashboard
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Runtime -----------------------------------------------------------------
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    APP_ENV=production \
    PORT=8000

# Mirrors the repository: /app/backend (Python, the working directory) and
# /app/frontend/dist (the dashboard the API serves)
WORKDIR /app/backend

# The commit being deployed (no .git in the image): /api/system and Sentry's release
ARG GIT_COMMIT=""
ENV GIT_COMMIT=$GIT_COMMIT

# Exact, hash-checked dependency versions (the same lock CI installs)
COPY backend/requirements.txt ./
RUN pip install --require-hashes -r requirements.txt

# Chromium plus the system libraries it needs (this stage runs as root), and
# git: repository ingestion clones with it, and fix patches and deploy checks use it
RUN python -m playwright install --with-deps chromium \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./
COPY backend/app/ app/
COPY backend/agents/ agents/
COPY backend/engine/ engine/
COPY backend/ingestion/ ingestion/
COPY backend/security/ security/
RUN pip install --no-deps -e .
COPY --from=dashboard /src/frontend/dist /app/frontend/dist

# Run unprivileged; data/ holds the offline JSON store and ingestion clones
RUN useradd --create-home --uid 10001 testsphere \
    && mkdir -p data artifacts \
    && chown -R testsphere data artifacts
USER testsphere

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health', timeout=4)"

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --no-access-log"]
