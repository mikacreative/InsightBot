"""Pure product view models shared by Streamlit UI and Agent tools."""

from __future__ import annotations

from typing import Any

from insightbot.domain import TaskSpec, TaskVersion
from insightbot.feed_health import describe_feed_issue


_SENSITIVE_PATH_PARTS = (
    "secret",
    "api_key",
    "apikey",
    "token",
    "password",
    "webhook",
    "webhook_url",
)


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return value
    return {}


def _task_spec_dict(task_spec: TaskSpec | dict[str, Any]) -> dict[str, Any]:
    data = _as_dict(task_spec)
    if "quality_policy" in data:
        return data
    if isinstance(task_spec, TaskSpec):
        return task_spec.to_dict()
    return data


def _risk_summary(validation: dict[str, Any], latest_run: dict[str, Any] | None) -> dict[str, Any]:
    issues = list(validation.get("issues", []) or [])
    diagnosis = (latest_run or {}).get("diagnosis") or {}
    findings = list(diagnosis.get("findings", []) or [])
    error_count = sum(1 for item in issues if item.get("severity") == "error")
    warning_count = sum(1 for item in issues if item.get("severity") == "warning")
    error_count += sum(1 for item in findings if item.get("severity") == "error")
    warning_count += sum(1 for item in findings if item.get("severity") == "warning")
    top_messages = [
        item.get("message") or item.get("label") or item.get("code") or item.get("type")
        for item in [*issues, *findings]
        if item.get("message") or item.get("label") or item.get("code") or item.get("type")
    ]
    return {
        "error_count": error_count,
        "warning_count": warning_count,
        "top_messages": top_messages[:3],
    }


def _status(validation: dict[str, Any], latest_run: dict[str, Any] | None) -> tuple[str, str]:
    if validation.get("needs_revalidation") or validation.get("summary", {}).get("needs_revalidation"):
        return "Config Changed", "配置已变更，建议重新 Dry Run。"
    if not validation.get("is_runnable", False):
        return "Needs Review", "任务配置还不完整。"
    if latest_run and latest_run.get("ok") is False:
        return "Failed", "最近一次运行失败。"
    if latest_run and not str(latest_run.get("final_markdown") or "").strip():
        run_trace = latest_run.get("run_trace") or {}
        render_stage = next((stage for stage in run_trace.get("stages", []) if stage.get("stage") == "render"), {})
        if render_stage.get("output_count") == 0 or latest_run.get("selected_count") == 0:
            return "No Output", "最近一次运行没有生成可推送内容。"
    return "Ready", "任务可运行。"


def _is_sensitive_path(path: str) -> bool:
    normalized = path.lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_PATH_PARTS)


def build_human_diagnosis(
    task_card: dict[str, Any] | None,
    run_evidence: dict[str, Any] | None,
    source_health: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build one sentence of operator-facing diagnosis from shared evidence."""
    task_card = task_card or {}
    run_evidence = run_evidence or {}
    source_health = source_health or {}
    status = task_card.get("status")
    source_errors = int(source_health.get("error_count") or 0)
    source_stale = int(source_health.get("stale_count") or 0)

    if status == "Needs Review":
        message = "任务配置还不完整，先处理配置阻断项。"
        severity = "error"
        next_action = "进入 Configure 修复任务、频道或调度配置。"
    elif status == "Config Changed":
        message = "任务配置已变更，现有运行证据可能过期。"
        severity = "warning"
        next_action = "先 Dry Run，再决定是否发送。"
    elif status == "Failed":
        message = "最近一次运行失败，需要查看 RunTrace 和日志定位失败阶段。"
        severity = "error"
        next_action = "进入 Investigate 查看失败阶段、诊断和日志。"
    elif status == "No Output":
        message = "抓取或筛选链路没有产出最终内容，可能是信源质量不足或筛选标准偏严。"
        severity = "warning"
        next_action = "检查 source health、候选数量、AI 筛选和最终输出。"
    elif source_errors:
        message = f"任务可运行，但有 {source_errors} 个信源错误，可能影响候选覆盖。"
        severity = "warning"
        next_action = "先查看 source health；如核心信源异常，建议修复后再发送。"
    elif source_stale and not run_evidence.get("has_output"):
        message = f"有 {source_stale} 个信源无更新，且最近没有可预览输出。"
        severity = "warning"
        next_action = "刷新健康度或补充信源后重新 Dry Run。"
    elif run_evidence.get("has_output"):
        message = "运行证据和输出预览可用，可以做发送前确认。"
        severity = "ok"
        next_action = "确认目标频道和 TaskVersion 后 Run & Send。"
    else:
        message = "任务可运行，但还缺少最新 Dry Run 证据。"
        severity = "info"
        next_action = "先 Dry Run 生成候选、诊断和输出预览。"

    return {
        "severity": severity,
        "message": message,
        "next_action": next_action,
    }


def build_run_evidence(run_record_or_command_result: dict[str, Any] | Any | None) -> dict[str, Any]:
    """Build a compact, JSON-safe run evidence view."""
    record = _as_dict(run_record_or_command_result)
    if "run_result" in record and record.get("run_result"):
        merged = dict(record["run_result"])
        if record.get("run_trace"):
            merged["run_trace"] = record["run_trace"]
        if record.get("diagnosis"):
            merged["diagnosis"] = record["diagnosis"]
        if record.get("task_version"):
            merged["task_version_id"] = record["task_version"].get("version_id")
        record = merged

    run_trace = record.get("run_trace") or record.get("_run_trace") or {}
    diagnosis = record.get("diagnosis") or record.get("_diagnosis") or {}
    stages = run_trace.get("stages", []) or []
    stage_counts = {
        stage.get("stage"): {
            "input": stage.get("input_count", 0),
            "output": stage.get("output_count", 0),
            "warnings": len(stage.get("warnings", []) or []),
            "errors": len(stage.get("errors", []) or []),
        }
        for stage in stages
        if stage.get("stage")
    }
    final_markdown = str(record.get("final_markdown") or run_trace.get("final_markdown") or "")
    return {
        "run_id": record.get("run_id") or run_trace.get("run_id"),
        "task_id": record.get("task_id") or run_trace.get("task_id"),
        "task_version_id": record.get("task_version_id") or run_trace.get("task_version_id"),
        "trigger_type": record.get("trigger_type") or run_trace.get("trigger_type") or ("dry_run" if record.get("dry_run") else "manual"),
        "ok": bool(record.get("ok", False)),
        "pipeline": record.get("pipeline") or run_trace.get("pipeline"),
        "stage_counts": stage_counts,
        "diagnosis": diagnosis,
        "channel_results": list(record.get("channel_results") or run_trace.get("channel_results") or []),
        "output_preview": final_markdown[:1200],
        "has_output": bool(final_markdown.strip()),
        "result_fingerprint": record.get("result_fingerprint") or run_trace.get("result_fingerprint"),
    }


def build_source_health_summary(health: dict[str, Any] | None) -> dict[str, Any]:
    """Build a source health summary safe for UI and Agent tool output."""
    payload = health or {}
    counts = payload.get("counts", {}) or {}
    failing: list[dict[str, Any]] = []
    for category in payload.get("categories", []) or []:
        for feed in category.get("feeds", []) or []:
            if feed.get("status") in {"error", "stale"}:
                failing.append(
                    {
                        "category": category.get("category"),
                        "name": feed.get("name") or feed.get("source_name") or feed.get("url"),
                        "url": feed.get("url"),
                        "status": feed.get("status"),
                        "error_type": feed.get("error_type"),
                        "error_message": feed.get("error_message"),
                        "latest_pub": feed.get("latest_pub"),
                        "diagnosis": describe_feed_issue(feed),
                    }
                )
    return {
        "source_count": counts.get("total", sum(counts.get(key, 0) for key in ("ok", "stale", "error"))),
        "ok_count": counts.get("ok", 0),
        "stale_count": counts.get("stale", 0),
        "error_count": counts.get("error", 0),
        "checked_at": payload.get("checked_at"),
        "is_stale": bool(payload.get("is_stale", False)),
        "top_failing_sources": failing[:5],
    }


def build_change_proposal(changeset: dict[str, Any] | Any | None, *, current_version_id: str | None = None) -> dict[str, Any]:
    """Build a human-readable ChangeProposal from a Domain ChangeSet."""
    payload = _as_dict(changeset)
    operations = list(payload.get("operations", []) or [])
    diff_lines: list[str] = []
    for op in operations[:12]:
        path = op.get("path") or "/"
        action = op.get("op") or "change"
        before = op.get("before")
        after = op.get("after")
        if op.get("sensitive") or _is_sensitive_path(str(path)):
            before = "<redacted>"
            after = "<redacted>"
        diff_lines.append(f"{action} {path}: {before!r} -> {after!r}")
    if len(operations) > 12:
        diff_lines.append(f"...and {len(operations) - 12} more changes")

    base_version = payload.get("base_version_id")
    stale = bool(current_version_id and base_version and current_version_id != base_version)
    risk_level = payload.get("risk_level") or "medium"
    return {
        "changeset_id": payload.get("changeset_id"),
        "task_id": payload.get("task_id"),
        "intent": payload.get("intent") or "Update task configuration",
        "risk_level": risk_level,
        "base_version_id": base_version,
        "target_version_id": payload.get("target_version_id"),
        "current_version_id": current_version_id,
        "is_stale": stale,
        "approval_required": True,
        "operation_count": len(operations),
        "human_readable_diff": diff_lines,
        "summary": f"{len(operations)} 项配置变更，风险等级 {risk_level}。",
    }


def build_task_card(
    task_spec: TaskSpec | dict[str, Any],
    validation: dict[str, Any] | None,
    latest_run: dict[str, Any] | None,
    latest_success: dict[str, Any] | None,
    health: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the primary human/agent task card view."""
    spec = _task_spec_dict(task_spec)
    validation = validation or {}
    latest_run = latest_run or None
    status, status_reason = _status(validation, latest_run)
    schedule = spec.get("schedule", {}) or {}
    health_summary = build_source_health_summary(health)
    version_id = None
    if isinstance(task_spec, TaskSpec):
        version_id = TaskVersion.from_spec(task_spec).version_id
    return {
        "task_id": spec.get("task_id"),
        "name": spec.get("name") or spec.get("task_id"),
        "enabled": bool(spec.get("enabled", False)),
        "status": status,
        "status_reason": status_reason,
        "next_run": {
            "hour": schedule.get("hour"),
            "minute": schedule.get("minute"),
            "day_of_week": schedule.get("day_of_week"),
        },
        "last_run": build_run_evidence(latest_run) if latest_run else None,
        "last_success": build_run_evidence(latest_success) if latest_success else None,
        "risk_summary": _risk_summary(validation, latest_run),
        "source_health": health_summary,
        "task_version_id": validation.get("summary", {}).get("task_version_id") or version_id,
        "channels": list(spec.get("channels", []) or []),
        "sections": list((spec.get("sections", {}) or {}).keys()),
    }


def build_workspace_state(
    tasks: dict[str, Any],
    selected_task_id: str | None,
    histories: dict[str, Any] | None,
    health: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the shared workbench state used by UI and internal Tool API."""
    histories = histories or {}
    cards: list[dict[str, Any]] = []
    run_evidence_by_task: dict[str, dict[str, Any]] = {}
    source_health_by_task: dict[str, dict[str, Any]] = {}
    for task_id, task_payload in (tasks or {}).items():
        task_history = histories.get(task_id, {}) if isinstance(histories.get(task_id, {}), dict) else {}
        task_health = health.get(task_id) if isinstance(health, dict) and task_id in health else health
        validation = task_history.get("validation", {"is_runnable": True, "issues": [], "summary": {}})
        try:
            spec = task_payload if isinstance(task_payload, TaskSpec) else TaskSpec.from_task_definition(task_id, task_payload)
        except Exception as exc:
            raw = task_payload if isinstance(task_payload, dict) else {}
            spec = {
                "task_id": task_id,
                "name": str(raw.get("name") or task_id),
                "enabled": bool(raw.get("enabled", False)),
                "channels": list(raw.get("channels") or []),
                "sections": raw.get("sections", {}) if isinstance(raw.get("sections"), dict) else {},
                "schedule": raw.get("schedule", {}) if isinstance(raw.get("schedule"), dict) else {},
            }
            validation = {
                "is_runnable": False,
                "issues": [
                    {
                        "severity": "error",
                        "message": f"任务配置无法读取：{exc}",
                    }
                ],
                "summary": {},
            }
        run_evidence = build_run_evidence(task_history.get("latest_run"))
        health_summary = build_source_health_summary(task_health)
        run_evidence_by_task[task_id] = run_evidence
        source_health_by_task[task_id] = health_summary
        cards.append(
            build_task_card(
                spec,
                validation,
                task_history.get("latest_run"),
                task_history.get("latest_success"),
                task_health,
            )
        )
    selected = selected_task_id if selected_task_id in (tasks or {}) else (cards[0]["task_id"] if cards else None)
    selected_task_card = next((card for card in cards if card.get("task_id") == selected), None)
    selected_run_evidence = run_evidence_by_task.get(selected or "", build_run_evidence(None))
    selected_source_health = source_health_by_task.get(selected or "", build_source_health_summary(None))
    return {
        "selected_task_id": selected,
        "task_cards": cards,
        "selected_task_card": selected_task_card,
        "selected_run_evidence": selected_run_evidence,
        "selected_source_health": selected_source_health,
        "human_diagnosis": build_human_diagnosis(selected_task_card, selected_run_evidence, selected_source_health),
        "active_count": sum(1 for card in cards if card.get("enabled")),
        "risk_count": sum(1 for card in cards if card.get("status") != "Ready"),
    }
