"""TestSphere-AI — codebase ingestion (module 5.1): source → project blueprint."""

from ingestion.analyzer import Blueprint, analyze_repo
from ingestion.source import (
    SourceError,
    clone,
    is_git_url,
    repo_name,
    resolve_local,
    validate_git_url,
)
from ingestion.vulns import as_findings, check_dependencies, pinned_packages

__all__ = ["Blueprint", "analyze_repo", "SourceError", "clone", "is_git_url", "repo_name", "resolve_local", "validate_git_url",
           "as_findings", "check_dependencies", "pinned_packages"]
