from typing import Any


def _issue(*, code: str, level: str, message: str, field_path: str) -> dict[str, str]:
    return {
        "code": code,
        "level": level,
        "message": message,
        "field_path": field_path,
    }


def validate_task_definition(task_id: str, task_def: dict[str, Any], channels_data: dict[str, Any]) -> dict[str, Any]:
    feeds = task_def.get("feeds", {}) or {}
    search = task_def.get("search", {}) or {}
    schedule = task_def.get("schedule", {}) or {}
    channels = task_def.get("channels", []) or []
    pipeline = task_def.get("pipeline", "editorial")
    pipeline_config = task_def.get("pipeline_config", {}) or {}
    known_channels = set((channels_data.get("channels", {}) or {}).keys())

    issues: list[dict[str, str]] = []

    if not feeds:
        issues.append(
            _issue(
                code="missing_categories",
                level="error",
                message="当前任务还没有任何板块。",
                field_path="feeds",
            )
        )

    feed_count = 0
    for category, feed_data in feeds.items():
        rss_list = [item for item in (feed_data or {}).get("rss", []) if str(item).strip()]
        feed_count += len(rss_list)
        if not rss_list:
            issues.append(
                _issue(
                    code="missing_feed_rss",
                    level="error",
                    message=f"板块「{category}」还没有配置 RSS 源。",
                    field_path=f"feeds.{category}.rss",
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
                field_path="search.queries",
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
            "category_count": len(feeds),
            "feed_count": feed_count,
            "channel_count": len(channels),
            "has_schedule": "hour" in schedule and "minute" in schedule,
            "search_query_count": len([item for item in search.get("queries", []) if str((item or {}).get("keywords", "")).strip()]),
            "pipeline": pipeline,
        },
    }
