# TestSphere-AI Backend Architecture & API Specification

## 1. Architectural Overview

TestSphere-AI's backend serves as the persistence, API coordination, and lifecycle management layer of the platform. Built on **FastAPI** with **Firebase Cloud Firestore** for persistence, it provides asynchronous and synchronous API endpoints, document storage behind a swappable `Store` interface, schema validation via Pydantic v2, and bidirectional bridge interfaces connecting AI test planning with headless browser automation.

```
                           +-------------------------------------+
                           |            Clients / UI             |
                           +------------------+------------------+
                                              |
                                HTTP REST / SSE Streaming
                                              v
                           +-------------------------------------+
                           |         FastAPI Application         |
                           |          (backend/main.py)          |
                           +------------------+------------------+
                                              |
                     +------------------------+------------------------+
                     |                                                 |
                     v                                                 v
         +-----------------------+                         +-----------------------+
         |     REST Routers      |                         |   Workflow / Stream   |
         |  (backend/api/*.py)   |                         | (backend/api/workflow)|
         +-----------+-----------+                         +-----------+-----------+
                     |                                                 |
                     v                                                 v
         +-----------------------+                         +-----------------------+
         |     Service Layer     |                         |  Orchestration Bridge |
         |(backend/services/*.py)|                         | (backend/orchestration|
         +-----------+-----------+                         +-----------+-----------+
                     |                                                 |
                     v                                                 +--------+
         +-----------------------+                                              |
         |   Store interface     |                                              v
         | (backend/database/)   |                                   +---------------------+
         +-----------+-----------+                                   | Member 1 (Agents)   |
                     |                                               | Member 2 (Engine)   |
                     v                                               +---------------------+
         +-----------------------+
         |  Cloud Firestore      |
         | (local JSON offline)  |
         +-----------------------+
```

---

## 2. Storage & Data Model

All persistence goes through the `Store` interface in [`backend/database/store.py`](../backend/database/store.py):
named collections of documents with integer ids, equality filters and ordering. Backends:

| `DATABASE_BACKEND` | Implementation | Use |
| --- | --- | --- |
| `firestore` | `FirestoreStore` (firebase-admin) | Production. Credentials from `FIREBASE_CREDENTIALS` |
| `local` | `LocalStore` (JSON file, atomic writes) | Offline local development (`LOCAL_DB_PATH`) |
| `memory` | `MemoryStore` | Tests |

Every backend passes the same contract tests (`tests/backend/test_store.py`), including Firestore via the official emulator.
Ids are per-collection counters (in Firestore: `_meta/counters`, incremented transactionally); every document has
`id`, `created_at` and `updated_at` (ISO 8601 UTC strings).

### Collections

| Collection | Fields | Parent (cascade delete) |
| --- | --- | --- |
| `projects` | `name`, `description` | — |
| `applications` | `project_id`, `name`, `base_url`, `description` | project |
| `test_cases` | `application_id`, `external_id`, `name`, `description` (JSON: planned steps + page analysis), `category`, `priority`, `version` | application |
| `test_executions` | `test_case_id`, `status` (`PENDING`/`RUNNING`/`PASSED`/`FAILED`/`HEALED`), `started_at`, `completed_at`, `duration_ms`, `error_message` | test case |
| `security_findings` | `key` (check + component), `target_url`, `check_id`, `severity`, `title`, `data` (finding JSON), `status`, `retest_result`, `approved_by`, `approved_at`, `first_seen`, `last_seen` | — |
| `audit_events` | `at`, `actor`, `kind`, `level`, `message`, `ref` | — (append-only) |
| `codebase_blueprints` | `source`, `name`, `data` (blueprint JSON) | — |
| `agent_memory` | `kind` (`execution`/`element`/`healing`), `data` (record JSON) | — |

Firestore has no foreign keys, so the services implement the cascades: deleting a project deletes its applications,
their test cases and those test cases' executions.

---

## 3. Service Layer Architecture

The service layer in [`backend/services/`](file:///backend/services/) enforces transaction atomicity, business logic, and error boundaries:

- **`ProjectService`** (`backend/services/project_service.py`):
  Manages workspace creation, retrieval, updates, and cascading teardown.
- **`ApplicationService`** (`backend/services/application_service.py`):
  Handles target application configurations and URL normalization.
- **`TestCaseService`** (`backend/services/test_case_service.py`):
  Validates incoming test case structures, checks element reference integrity, and persists generated tests.
- **`TestExecutionService`** (`backend/services/test_execution_service.py`):
  Logs execution runs, tracks step statuses, records metrics, and archives visual artifacts.
- **`ServiceExceptions`** (`backend/services/exceptions.py`):
  Centralized domain exception hierarchy (`EntityNotFoundError`, `ValidationError`, `ConflictError`) cleanly mapped to standard HTTP status codes.

---

## 4. REST API Specification

The FastAPI application mounts routes defined in [`backend/api/`](file:///backend/api/):

### 4.1 Project Endpoints (`/api/projects`)
- `POST /api/projects`: Create a new project.
- `GET /api/projects`: List all active projects.
- `GET /api/projects/{project_id}`: Retrieve project details and associated suites.
- `PUT /api/projects/{project_id}`: Update project metadata.
- `DELETE /api/projects/{project_id}`: Delete project and associated tests.

### 4.2 Application Endpoints (`/api/applications`)
- `POST /api/applications`: Register a target web application.
- `GET /api/applications`: List applications under a project.
- `GET /api/applications/{app_id}`: Retrieve specific application details.
- `DELETE /api/applications/{app_id}`: Deregister an application.

### 4.3 Test Case Endpoints (`/api/test-cases`)
- `POST /api/test-cases`: Create a new test case with structured steps.
- `GET /api/test-cases`: List test cases with optional filter by project or priority.
- `GET /api/test-cases/{case_id}`: Retrieve full test case with step definitions.
- `PUT /api/test-cases/{case_id}`: Update test case parameters or steps.
- `DELETE /api/test-cases/{case_id}`: Remove test case.

### 4.4 Test Execution Endpoints (`/api/test-executions`)
- `POST /api/test-executions`: Trigger execution run for a test case.
- `GET /api/test-executions`: Query execution history with pagination.
- `GET /api/test-executions/{execution_id}`: Get execution details, step logs, and screenshots.

### 4.5 Orchestration & Workflow Stream (`/api/workflow`)
- `POST /api/workflow/plan-and-execute`: High-level endpoint accepting application context, generating tests via AI agents, executing on Playwright, and applying self-healing if needed.
- `GET /api/workflow/stream/{execution_id}`: **Server-Sent Events (SSE)** endpoint streaming real-time execution steps, locator healing events, and screenshot URLs to the frontend dashboard.

---

## 5. Security & Error Handling

- **CORS Middleware**: Configured in [`backend/main.py`](file:///backend/main.py) with configurable origins for local development and production deployments.
- **Request Validation**: Pydantic v2 schemas in [`backend/api/schemas.py`](file:///backend/api/schemas.py) strictly validate payloads before passing to services.
- **Database Session Lifecycles**: Dependency injection via `get_db()` ensures thread-safe session allocation and deterministic teardown upon request completion.
