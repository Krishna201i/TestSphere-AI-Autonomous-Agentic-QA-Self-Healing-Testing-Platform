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

**Dashboard hosted apart from the API (e.g. Vercel + Render).** Build the dashboard with `VITE_API_URL` set to the
backend's URL (e.g. `https://your-api.onrender.com`; in Vercel: Project → Settings → Environment Variables, then
redeploy), and set `CORS_ORIGINS` on the backend to the dashboard's origin. Without `VITE_API_URL` the dashboard
calls its own host, which answers with the app's HTML page; the dashboard then says so instead of failing to parse
it. For a local build, `VITE_API_URL` is read from the `.env` at the repository root. Google and GitHub sign-in use a
pop-up; when the browser blocks it, the dashboard asks the user to allow pop-ups. The redirect fallback is only used
when `FIREBASE_AUTH_DOMAIN` is the dashboard's own domain (with `/__/auth/*` proxied to
`<project>.firebaseapp.com`, as in Firebase's *redirect best practices*), because browsers that partition
third-party storage return from a redirect to another domain signed out.
GitHub push webhooks are per project: the Automation page shows each project's payload URL and secret.

### 2.2 AI Agent Settings
| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `LLM_PROVIDER` | `mock` | `mock` (offline, deterministic) or `api` (any OpenAI-compatible chat API), or `local` (an OpenAI-compatible server on this machine such as Ollama; no key needed, `LLM_BASE_URL` defaults to `http://localhost:11434/v1`). With `mock`, test generation and healing use only the built-in rules: the AI planner, AI healer and failure analyzer stay off |
| `LLM_API_KEY` | `""` | API key for the configured endpoint (required if `LLM_PROVIDER=api`) |
| `LLM_BASE_URL` | OpenAI | Base URL of the OpenAI-compatible endpoint (OpenAI, Anthropic, Gemini, Groq, OpenRouter) |
| `LLM_MODEL` | `mock-model` | Model identifier sent to the endpoint |
| `LLM_TEMPERATURE` | `0.2` | Sampling temperature for test synthesis and healing decisions |
| `LLM_MAX_TOKENS` | `4096` | Max output tokens per request |
| `LLM_TIMEOUT` | `60` | Request timeout in seconds |
| `LLM_MAX_RETRIES` | `2` | Retries for transient errors (timeouts, 429, 5xx, network) |
| `AGENT_MEMORY_BACKEND` | `database` | `database` persists healing memory in the configured store (survives restarts); `memory` keeps it in-process |
| `AGENT_MEMORY_MAX_RECORDS` | `2000` | Newest healing records loaded at start-up; more remembers older heals but costs that many database reads per restart |
| `INGEST_WORKSPACE` | `./data/repos` | Where ingested repositories are cloned |
| `INGEST_GIT_HOSTS` | `github.com,gitlab.com,bitbucket.org` | Hosts public repositories may be cloned from (https only) |
| `INGEST_MAX_FILES` / `INGEST_MAX_FILE_BYTES` / `INGEST_CLONE_TIMEOUT` | `20000` / `1000000` / `120` | Safety caps per repository: files analyzed, bytes read per file, seconds a clone may take |
| `INGEST_ALLOW_LOCAL_PATHS` | `true` locally in development; `false` on Render/Heroku/Railway/Fly/Cloud Run unless set | Accept local folder paths for ingestion (reads the server's disk); never enable on a public server |
| `SECURITY_SCAN_ALLOWED_HOSTS` | `""` | Extra hosts the passive scanner may contact (loopback always allowed) |
| `RATE_LIMIT_RUNS_PER_MINUTE` | `10` | Runs, scans and clones each user may start per minute (`0` disables); over it the API answers 429 |
| `RATE_LIMIT_BACKEND` | `memory` | `memory` counts per process (right for one instance); `database` shares the count between instances, at one read and one write per run start. With several API instances, also route each `/api/workflow/stream` client back to the instance running its workflow (sticky sessions): live run events stay in that instance's memory |
| `ENGINE_MAX_BROWSERS` | `2` | Browser instances that may run at once; further runs wait for a slot |
| `ENGINE_BROWSER` | `chromium` | Browser tests run in: `chromium`, `firefox` or `webkit` (Safari's engine). The image installs Chromium only; another browser is downloaded on its first run, or add `python -m playwright install --with-deps <browser>` to the build. The outbound request guard covers all three |
| `ENGINE_VIEWPORT` | `1280x720` | Browser window as WIDTHxHEIGHT (e.g. `390x844` for a phone). Changing it changes screenshots, so visual baselines are taken again |
| `VISUAL_REGRESSION` / `VISUAL_DIFF_THRESHOLD` | `true` / `0.02` | Compare each passing run's screenshot with the test's approved baseline; more than this share of changed pixels is a visual change to review |
| `VISUAL_FULL_PAGE` | `false` | Screenshot the whole page instead of the window, so changes below the fold count; a page that grows or shrinks is compared over the shared rows, the added or removed rows counting as changed |
| `PIPELINE_LINK_PAGES` / `PIPELINE_ROUTE_PAGES` | `3` / `5` | Same-site linked pages and codebase GET routes each pipeline run tests besides the target page |
| `PIPELINE_DEEP_PAGES` | `3` | How many of those pages are analyzed for content checks (title, heading, form controls present); the rest only must render. Forms on them are never submitted |
| `PIPELINE_AI_PLANNER` | `auto` | `auto`: AI-written tests when a real model is configured; `on` / `off` force it |
| `PIPELINE_EXECUTION` | `inline` | `inline`: pipeline runs execute in the API process. `worker`: the API only queues them and a separate `python -m backend.worker` service executes them (and runs the scheduler). Requires Firestore. See §3.1 |
| `WORKER_POLL_SECONDS` / `WORKER_HEARTBEAT_SECONDS` / `WORKER_STALE_SECONDS` | `5` / `30` / `600` | Worker queue polling; heartbeat while a run executes; a running run silent for longer than the stale limit is marked interrupted |
| `DASHBOARD_URL` | Render's `RENDER_EXTERNAL_URL`, else `""` | Public address of the dashboard, used for "Open run" links in Slack alerts |
| `PRIVACY_CONTACT` | `""` | E-mail or URL users contact about their data, shown on the dashboard's privacy notice (`#/privacy`, readable before sign-in). Without it the notice says "the operator of this server" |
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
| `ARTIFACTS_DIR` | `./data/artifacts` | With `ARTIFACT_STORE=local`: where screenshots, DOM snapshots and traces are kept per execution (the engine's own working copies under `./artifacts` are removed once stored) |

### 2.3a Run evidence and integrations
| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `ARTIFACT_STORE` | `local` | `local` keeps run artifacts on this server's disk (lost on redeploy on most hosts; not shared with a separate worker). `gcs` stores them in a Cloud Storage bucket: use it in production |
| `ARTIFACT_BUCKET` | `""` | With `gcs`: the bucket, e.g. the Firebase project's default `<project-id>.appspot.com` (Firebase console → Storage). The service account in `FIREBASE_CREDENTIALS` needs *Storage Object Admin* on it. Artifacts live under `testsphere-artifacts/` |
| `ARTIFACT_TRACES` | `true` | Record a Playwright trace (`.zip`, typically 1–5 MB) for every test run, downloadable from the run page |
| `ARTIFACT_RETENTION_DAYS` | `30` | Delete artifacts after this many days (`0` keeps them until the execution or account is deleted). On GCS this is a bucket lifecycle rule set on first use (needs `storage.buckets.update`; otherwise add the rule in the console) |

**Fix patches** (Security → Remediation → *Fix patch for your code*): the open findings of a site become a
`git apply`-able diff against its repository (the project's *Git repository*, or one pasted in the form).
The server shallow-clones it into `INGEST_WORKSPACE/patches/` (same host allow-list as ingestion, so `git`
must be installed), edits a temporary copy, checks that edited Python/JavaScript still parses, stores the
result in `fix_patches` and deletes the clone. Supported: FastAPI/Starlette and Flask (header hook, CORS
allow-list, cookie flags, `uvicorn.run(server_header=False)`), Django settings, Express (header middleware,
`cors()`, `res.cookie` options, `x-powered-by`), nginx `server {}` blocks. Anything else is listed as a manual change.

**Verified deploy** (loop stage 6; Autopilot → project → Settings → *Verified deploy*, or *Deploy* on the
project row): TestSphere calls the project's deploy hook, records the commit (`git ls-remote` of its
repository), waits until the health URL (default: app URL) answers healthily `DEPLOY_HEALTHY_CHECKS` times in
a row — after the page changes, or after `DEPLOY_SETTLE_SECONDS` if it never does — within
`DEPLOY_TIMEOUT_SECONDS`, then runs the project's smoke tests. If health or smoke tests fail it calls the
rollback hook, or with a Render deploy hook redeploys the last verified commit (`&ref=<sha>`), and checks
health again. Hooks may only go to Render, Vercel, Netlify or hosts in `DEPLOY_HOOK_HOSTS` (https, no
redirects). *Deploy and verify automatically after a run passes* closes the loop. Deployments run in the
API process, also with `PIPELINE_EXECUTION=worker`.

| Variable | Default | Description |
| :--- | :--- | :--- |
| `DEPLOY_HOOK_HOSTS` | `""` | Extra hosts deploy/rollback hooks may call (comma-separated) |
| `DEPLOY_TIMEOUT_SECONDS` | `600` | How long a deploy (and a rollback) may take to become healthy |
| `DEPLOY_SETTLE_SECONDS` | `90` | When the health URL looks the same before and after, wait this long before trusting it |
| `DEPLOY_POLL_SECONDS` / `DEPLOY_HEALTHY_CHECKS` | `10` / `3` | Health check interval and how many healthy answers in a row count |

**GitHub** (Profile → Integrations): each user connects GitHub with a fine-grained personal access token
limited to chosen repositories, with *Contents*, *Pull requests* and *Commit statuses* set to Read and write.
The token is checked with GitHub, encrypted with `TOKEN_ENCRYPTION_KEY` and never returned to the browser.
Then **Open pull request** on a fix patch creates a branch `testsphere/fix-<id>` from the commit the patch was
built against, with one commit of the patched files, and a pull request to the default branch. Runs started
by a GitHub push set a `TestSphere` commit status (success / failure / error) linking to the run page.

**Private repositories.** Fetching a repository (ingestion, pipeline runs, fix patches, the commit a deploy
ships) uses the owner's credentials for that host: the connected GitHub token for `github.com`, or a Git
credential saved for another allowed host with `PUT /api/integrations/git-credentials`
(`{"host": "gitlab.com", "token": "glpat-…"}`; for Bitbucket an API token or access token, since app passwords
no longer work). The token is
stored encrypted, sent as an `Authorization` header scoped to that one host (never in the URL, `.git/config`
or error messages, and not after a redirect to another host), and used only for its owner's projects.
A GitHub token needs *Contents: Read* on the repository to clone it.

**GitHub sign-in.** With the GitHub provider enabled in Firebase (Authentication → Sign-in method → GitHub, using
a GitHub OAuth App whose callback URL is `https://<project>.firebaseapp.com/__/auth/handler`), the sign-in page
offers *Continue with GitHub*. Sign-in asks GitHub only for the user's identity. Repository access is separate:
**Connect with GitHub** in Profile → Integrations opens a GitHub window asking for the `repo` scope, links GitHub
to the account (or re-confirms it), and stores the token like a pasted one. Users who want access to only some
repositories can paste a fine-grained token instead. An email that already has an account with Google or a
password must sign in that way first; Firebase does not merge accounts by itself.

| Variable | Default | Description |
| :--- | :--- | :--- |
| `TOKEN_ENCRYPTION_KEY` | generated in `data/.token_key` locally; **required when hosted** | Fernet key for stored integration tokens. Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Changing it disconnects every user's GitHub |

Slack alerts are set per project in Autopilot → project → Settings: paste a Slack incoming-webhook URL
(Slack → Apps → *Incoming Webhooks*; only `https://hooks.slack.com/services/...` is accepted) and choose
"when a run fails or regresses" or "after every run". Each run page also offers a **JUnit XML** download
(`GET /api/pipelines/runs/{id}/junit`) for CI test dashboards.

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

### 3.1 Separate pipeline worker

By default pipeline runs (Autopilot, scheduled and webhook runs) execute inside the API process: one
service, fits a free host, but Chromium shares the API's memory and a restart interrupts queued runs.
With a worker:

1. Set `PIPELINE_EXECUTION=worker` on **both** the API and the worker (same environment otherwise,
   including Firestore credentials; the worker refuses to start without a shared database).
2. Run the worker: `python -m backend.worker` (Docker: `docker run --env-file .env testsphere python -m backend.worker`;
   Render: a *Background Worker* service with that start command, which needs a paid instance type).

The API then only queues runs. The worker claims the oldest queued run atomically (several workers never
take the same run), executes one at a time, refreshes `heartbeat_at`, and runs the scheduler, so
scheduled runs fire even while the API sleeps. A run whose worker died is marked interrupted, not re-run.
Interactive runs from the Pipeline page (`/api/workflow/*`) still execute in the API process.

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
