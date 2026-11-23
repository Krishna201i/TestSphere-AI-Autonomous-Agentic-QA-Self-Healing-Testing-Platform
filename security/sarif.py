"""
security/sarif.py
=================
Convert TestSphere-AI security findings to SARIF v2.1.0 (OASIS standard).

Compatible with GitHub Code Scanning, GitLab Security Dashboard, SonarQube,
and IDE SARIF viewers.
"""

from __future__ import annotations

from typing import Any

from security.findings import Finding, Severity

SARIF_SCHEMA = "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json"
SARIF_VERSION = "2.1.0"

_SEVERITY_TO_SARIF_LEVEL: dict[str, str] = {
    Severity.CRITICAL.value: "error",
    Severity.HIGH.value: "error",
    Severity.MEDIUM.value: "warning",
    Severity.LOW.value: "note",
    Severity.INFO.value: "note",
}


def _sarif_level(severity: str | Severity) -> str:
    sev_str = severity.value if isinstance(severity, Severity) else str(severity).lower()
    return _SEVERITY_TO_SARIF_LEVEL.get(sev_str, "warning")


def findings_to_sarif(
    findings: list[Finding | dict[str, Any]],
    *,
    tool_name: str = "TestSphere AI",
    tool_version: str = "1.0.0",
    information_uri: str = "https://github.com/Krishna201i/TestSphere-AI-Autonomous-Agentic-QA-Self-Healing-Testing-Platform",
) -> dict[str, Any]:
    """Convert findings into a standard SARIF v2.1.0 JSON document."""
    rules_dict: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []

    for item in findings:
        if isinstance(item, Finding):
            check_id = item.check_id
            title = item.title
            severity = item.severity
            component = item.component
            target_url = item.target_url
            evidence = item.evidence
            root_cause = item.root_cause
            recommendation = item.recommendation
            confidence = item.confidence
            status_val = item.status.value
            key_val = item.key
        elif isinstance(item, dict):
            check_id = str(item.get("check_id") or "UNKNOWN")
            title = str(item.get("title") or check_id)
            severity = item.get("severity") or "medium"
            component = str(item.get("component") or "")
            target_url = str(item.get("target_url") or "")
            evidence = item.get("evidence") or []
            root_cause = str(item.get("root_cause") or "")
            recommendation = str(item.get("recommendation") or "")
            confidence = float(item.get("confidence", 1.0))
            status_val = str(item.get("status") or "open")
            key_val = str(item.get("key") or "")
        else:
            continue

        level = _sarif_level(severity)
        sev_name = severity.value if isinstance(severity, Severity) else str(severity).lower()

        # Build rule definition once per unique check_id
        if check_id not in rules_dict:
            rule_entry: dict[str, Any] = {
                "id": check_id,
                "name": check_id.replace("-", ""),
                "shortDescription": {"text": title},
                "defaultConfiguration": {"level": level},
            }
            desc = root_cause or title
            if desc:
                rule_entry["fullDescription"] = {"text": desc}
            if recommendation:
                rule_entry["help"] = {"text": recommendation}
            rules_dict[check_id] = rule_entry

        # Result message
        msg_text = title
        if root_cause:
            msg_text = f"{title}: {root_cause}"
        elif recommendation:
            msg_text = f"{title}: {recommendation}"

        result_entry: dict[str, Any] = {
            "ruleId": check_id,
            "level": level,
            "message": {"text": msg_text},
            "properties": {
                "key": key_val,
                "severity": sev_name,
                "confidence": confidence,
                "status": status_val,
                "component": component,
                "evidence": evidence,
                "recommendation": recommendation,
            },
        }

        # Physical location (URL / resource / component)
        loc_uri = target_url or component
        if loc_uri:
            result_entry["locations"] = [
                {
                    "physicalLocation": {
                        "artifactLocation": {
                            "uri": loc_uri,
                        }
                    }
                }
            ]

        results.append(result_entry)

    rules_list = sorted(rules_dict.values(), key=lambda r: r["id"])

    return {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": tool_name,
                        "version": tool_version,
                        "informationUri": information_uri,
                        "rules": rules_list,
                    }
                },
                "results": results,
            }
        ],
    }
