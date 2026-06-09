from __future__ import annotations

from .models import DiagnosisReport, TaskSpec


def _field_path_for_finding(finding) -> str:
    for evidence in finding.evidence:
        if evidence.get("field_path"):
            return str(evidence["field_path"])
    field_map = {
        "missing_sections": "sections",
        "missing_sources": "sources",
        "missing_channels": "channels",
        "channel_not_found": "channels",
        "missing_schedule": "schedule",
        "missing_section_prompt": "sections.prompt",
    }
    return field_map.get(finding.type, "domain")


def validation_result_from_domain(spec: TaskSpec, report: DiagnosisReport) -> dict:
    """
    Convert Domain DiagnosisReport to the legacy validation_result shape used by
    Streamlit UI. This keeps UI migration incremental while moving validation
    ownership into the Domain Kernel.
    """
    issues = [
        {
            "code": finding.type,
            "level": finding.severity if finding.severity in {"error", "warning"} else "warning",
            "message": finding.message,
            "field_path": _field_path_for_finding(finding),
        }
        for finding in report.findings
        if finding.severity in {"error", "warning"}
    ]
    error_count = sum(1 for item in issues if item["level"] == "error")
    warning_count = sum(1 for item in issues if item["level"] == "warning")
    if error_count:
        status = "not_ready"
        is_runnable = False
    elif warning_count:
        status = "needs_attention"
        is_runnable = True
    else:
        status = "ready"
        is_runnable = True

    search_queries = spec.sources.get("search", {}).get("queries", []) or []
    return {
        "task_id": spec.task_id,
        "is_runnable": is_runnable,
        "status": status,
        "issues": issues,
        "summary": {
            "section_count": len(spec.sections),
            "rss_source_count": spec.enabled_source_count,
            "channel_count": len(spec.channels),
            "has_schedule": "hour" in spec.schedule and "minute" in spec.schedule,
            "search_query_count": len(search_queries),
            "pipeline": spec.pipeline,
            "task_version_id": None,
            "domain_diagnosis_id": report.diagnosis_id,
        },
        "domain_diagnosis": report.to_dict(),
    }

