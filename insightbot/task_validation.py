from typing import Any


from .config import normalize_task_definition


def _issue(*, code: str, level: str, message: str, field_path: str) -> dict[str, str]:
    return {
        "code": code,
        "level": level,
        "message": message,
        "field_path": field_path,
    }


def validate_task_definition(task_id: str, task_def: dict[str, Any], channels_data: dict[str, Any]) -> dict[str, Any]:
    task_def = normalize_task_definition(task_def)
    sources = task_def.get("sources", {}) or {}
    sections = task_def.get("sections", {}) or {}
    rss_sources = sources.get("rss", []) or []
    search = sources.get("search", {}) or {}
    schedule = task_def.get("schedule", {}) or {}
    channels = task_def.get("channels", []) or []
    pipeline = task_def.get("pipeline", "editorial")
    pipeline_config = task_def.get("pipeline_config", {}) or {}
    known_channels = set((channels_data.get("channels", {}) or {}).keys())

    issues: list[dict[str, str]] = []

    if not sections:
        issues.append(
            _issue(
                code="missing_sections",
                level="error",
                message="当前任务还没有任何栏目。",
                field_path="sections",
            )
        )

    rss_source_count = 0
    enabled_rss_sources = []
    for idx, source in enumerate(rss_sources):
        if not isinstance(source, dict):
            continue
        url = str(source.get("url", "")).strip()
        enabled = bool(source.get("enabled", True))
        if enabled and url:
            enabled_rss_sources.append(source)
            rss_source_count += 1
        elif enabled and not url:
            issues.append(
                _issue(
                    code="missing_source_url",
                    level="error",
                    message=f"RSS 信源 #{idx + 1} 缺少 URL。",
                    field_path=f"sources.rss[{idx}].url",
                )
            )

    for section_name, section_data in sections.items():
        if not str((section_data or {}).get("prompt", "")).strip():
            issues.append(
                _issue(
                    code="missing_section_prompt",
                    level="warning",
                    message=f"栏目「{section_name}」还没有填写筛选 Prompt。",
                    field_path=f"sections.{section_name}.prompt",
                )
            )

    if not enabled_rss_sources and not search.get("enabled", False):
        issues.append(
            _issue(
                code="missing_sources",
                level="error",
                message="当前任务没有任何可用信源：既没有启用 RSS，也没有启用搜索补充。",
                field_path="sources",
            )
        )

    if not channels:
        issues.append(
            _issue(
                code="missing_channels",
                level="error",
                message="当前任务未绑定任何频道。",
                field_path="channels",
            )
        )
    else:
        for channel_id in channels:
            if channel_id not in known_channels:
                issues.append(
                    _issue(
                        code="channel_not_found",
                        level="error",
                        message=f"任务引用的频道「{channel_id}」不存在。",
                        field_path="channels",
                    )
                )

    if "hour" not in schedule or "minute" not in schedule:
        issues.append(
            _issue(
                code="missing_schedule",
                level="error",
                message="当前任务缺少完整的调度时间。",
                field_path="schedule",
            )
        )

    if search.get("enabled") and not [item for item in search.get("queries", []) if str((item or {}).get("keywords", "")).strip()]:
        issues.append(
            _issue(
                code="missing_search_queries",
                level="warning",
                message="已启用搜索补充，但还没有有效 query。",
                field_path="sources.search.queries",
            )
        )

    if pipeline not in {"editorial", "classic"}:
        issues.append(
            _issue(
                code="invalid_pipeline",
                level="error",
                message=f"当前 pipeline 类型「{pipeline}」无效。",
                field_path="pipeline",
            )
        )
    elif pipeline == "editorial" and not pipeline_config:
        issues.append(
            _issue(
                code="missing_pipeline_config",
                level="warning",
                message="Editorial 任务尚未配置专属 pipeline 参数，将退回默认值。",
                field_path="pipeline_config",
            )
        )

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

    return {
        "task_id": task_id,
        "is_runnable": is_runnable,
        "status": status,
        "issues": issues,
        "summary": {
            "section_count": len(sections),
            "rss_source_count": rss_source_count,
            "channel_count": len(channels),
            "has_schedule": "hour" in schedule and "minute" in schedule,
            "search_query_count": len([item for item in search.get("queries", []) if str((item or {}).get("keywords", "")).strip()]),
            "pipeline": pipeline,
        },
    }
