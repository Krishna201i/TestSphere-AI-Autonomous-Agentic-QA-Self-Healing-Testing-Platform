# TestSphere-AI backend: FastAPI API (and the pipeline worker) + headless Chromium.
# The dashboard is a separate image (frontend/Dockerfile) that proxies /api here.
#   docker build -t testsphere-backend backend
#   docker run -p 8000:8000 --env-file .env testsphere-backend
#   docker run --env-file .env testsphere-backend python -m app.worker   # worker
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    APP_ENV=production \
    PORT=8000

# Same layout as the repository (/app/backend); there is no /app/frontend/dist
# here, so the API serves only the API
WORKDIR /app/backend

# Exact, hash-checked dependency versions (the same lock CI installs)
COPY requirements.txt ./
RUN pip install --require-hashes -r requirements.txt

# Chromium plus the system libraries it needs (this stage runs as root), and
# git: repository ingestion clones with it, and fix patches and deploy checks use it
RUN python -m playwright install --with-deps chromium \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app/ app/
COPY agents/ agents/
COPY engine/ engine/
COPY ingestion/ ingestion/
COPY security/ security/
RUN pip install --no-deps -e .

# Run unprivileged; data/ holds the offline JSON store, artifacts and ingestion clones
RUN useradd --create-home --uid 10001 testsphere \
    && mkdir -p data artifacts \
    && chown -R testsphere data artifacts
USER testsphere

# The commit being deployed (no .git in the image): /api/system and Sentry's release.
# Last, so a new commit does not invalidate the cached layers above
ARG GIT_COMMIT=""
ENV GIT_COMMIT=$GIT_COMMIT

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health', timeout=4)"

# --proxy-headers: behind the frontend's nginx (and Caddy in production), the
# client address and https come from X-Forwarded-*; the port is never published
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --no-access-log --proxy-headers --forwarded-allow-ips '*'"]
