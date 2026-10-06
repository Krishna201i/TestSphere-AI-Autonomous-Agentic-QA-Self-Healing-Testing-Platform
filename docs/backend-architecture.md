# TestSphere-AI Backend Architecture & API Specification

## 1. Architectural Overview

TestSphere-AI's backend serves as the persistence, API coordination, and lifecycle management layer of the platform. Built on **FastAPI** and **SQLAlchemy 2.0**, it provides high-throughput asynchronous and synchronous API endpoints, relational database persistence, schema validation via Pydantic v2, and bidirectional bridge interfaces connecting AI test planning with headless browser automation.

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
         |   SQLAlchemy Models   |                                              v
         | (backend/models/*.py) |                                   +---------------------+
         +-----------+-----------+                                   | Member 1 (Agents)   |
                     |                                               | Member 2 (Engine)   |
                     v                                               +---------------------+
         +-----------------------+
         |   Relational Store    |
         | (PostgreSQL / SQLite) |
         +-----------------------+
```

---

## 2. Database Schema & Data Models

The persistence schema is defined in [`backend/models/`](file:///backend/models/) using SQLAlchemy declarative mappings.

### 2.1 Project (`backend/models/project.py`)
Root multi-tenant container for test automation suites and configuration profiles.
- `id` (Integer, Primary Key)
- `name` (String, Indexed, Unique per tenant)
- `description` (Text, Optional)
- `created_at` (DateTime, Default UTC)
- `updated_at` (DateTime, Auto-updating UTC)
- Relationships:
  - `applications`: One-to-many relationship with `Application`
  - `test_cases`: One-to-many cascade relationship with `TestCase`

### 2.2 Application (`backend/models/application.py`)
Target system-under-test (SUT) metadata, base URLs, and authentication credentials.
- `id` (Integer, Primary Key)
- `project_id` (Integer, Foreign Key `projects.id`)
- `name` (String, Required)
- `base_url` (String, Target web app entrypoint)
- `description` (Text, Optional)
- `auth_config` (JSON / Dict, Stored credential hints or session tokens)
- `created_at` / `updated_at` (DateTime)

### 2.3 TestCase (`backend/models/test_case.py`)
Executable test definitions composed of sequential test steps.
- `id` (Integer, Primary Key)
- `project_id` (Integer, Foreign Key `projects.id`)
- `title` (String, Short descriptive label)
- `description` (Text, High-level intent)
- `category` (Enum: `SMOKE`, `REGRESSION`, `CRITICAL_PATH`, `EDGE_CASE`, `ACCESSIBILITY`)
- `priority` (Enum: `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`)
- `steps` (JSON / List of Dicts, Stored serialized `TestStep` definitions)
- `is_active` (Boolean, Default True)
- `created_at` / `updated_at` (DateTime)

### 2.4 TestExecution (`backend/models/test_execution.py`)
Historical run records with step-level telemetry, timing, and self-healing artifacts.
- `id` (Integer, Primary Key)
- `test_case_id` (Integer, Foreign Key `test_cases.id`)
- `status` (Enum: `PENDING`, `RUNNING`, `PASSED`, `FAILED`, `HEALED`, `ERROR`)
- `started_at` (DateTime, Execution start timestamp)
- `completed_at` (DateTime, Execution finish timestamp)
- `duration_ms` (Float, Total elapsed wall time)
- `step_results` (JSON, Detailed step breakdown with selectors, actions, screenshots)
- `healing_log` (JSON, Self-healing diagnosis, mutations, and retry outcomes)
- `error_message` (Text, Unhandled tracebacks or assertion error text)

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
