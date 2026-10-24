"""
TestSphere-AI — Data model names.

Entities are documents in these store collections (Firestore in production):

    projects            name, description
    applications        project_id, name, base_url, description
    test_cases          application_id, external_id, name, description, category, priority, version
    test_executions     test_case_id, status, started_at, completed_at, duration_ms, error_message
    security_findings   key, target_url, check_id, severity, title, data, status, retest_result, ...
    audit_events        at, actor, kind, level, message, ref
    codebase_blueprints source, name, data
    agent_memory        kind, data
    users               uid, email, display_name, organization, job_title, last_login_at
    pipeline_runs       project_id, trigger, status, stages, tests, summary, ...
    fix_patches         target_url, repo, commit, files, applied, manual, patch

Documents owned by a user also carry ``owner_uid`` (see backend/auth.py).

Every document also has ``id`` (integer), ``created_at`` and ``updated_at``.
"""

from backend.models.test_execution import TestExecutionStatus

PROJECTS = "projects"
APPLICATIONS = "applications"
TEST_CASES = "test_cases"
TEST_EXECUTIONS = "test_executions"
SECURITY_FINDINGS = "security_findings"
AUDIT_EVENTS = "audit_events"
BLUEPRINTS = "codebase_blueprints"
USERS = "users"
PIPELINE_RUNS = "pipeline_runs"
FIX_PATCHES = "fix_patches"

__all__ = [
    "TestExecutionStatus", "PROJECTS", "APPLICATIONS", "TEST_CASES", "TEST_EXECUTIONS",
    "SECURITY_FINDINGS", "AUDIT_EVENTS", "BLUEPRINTS", "USERS", "PIPELINE_RUNS", "FIX_PATCHES",
]
