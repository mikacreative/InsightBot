from __future__ import annotations

from typing import Any

import streamlit as st

from insightbot.channel_routes import normalize_channel_routes
from insightbot.channels import validate_channel_definition


def _render_readiness_chip(label: str, status: str, detail: str) -> None:
    css_class = {
        "ok": "ib-chip-success",
        "warn": "ib-chip-warning",
        "error": "ib-chip-error",
        "neutral": "ib-chip-neutral",
    }.get(status, "ib-chip-neutral")
    st.markdown(
        f'<div class="ib-chip-row"><span class="ib-chip {css_class}">{label}</span></div>',
        unsafe_allow_html=True,
    )
    st.caption(detail)


def _safe_get_task_schedule(task_def: dict | None) -> dict[str, int]:
    if not isinstance(task_def, dict):
        return {}
    schedule = task_def.get("schedule") or {}
    if not isinstance(schedule, dict):
        return {}
    return schedule


def _build_no_push_hint(run_summary: dict) -> str:
    if run_summary.get("runtime_errors"):
        return "检测到运行时异常，优先查看日志定位失败原因。"
    if run_summary.get("overall_no_push"):
        return "最近运行产生了“无推送”结论，请结合健康度和 Prompt 调试确认原因。"
    if run_summary.get("categories"):
        return "最近运行未判定为无推送，可侧重核验发送与归档通道。"
    return "无最近运行日志可参考。"


def analyze_task_execution_readiness(
    *,
    selected_task_id: str | None,
    selected_task: dict,
    task_validation: dict,
    task_state: dict | None,
    channels_data: dict,
    run_summary: dict | None = None,
    latest_run_record: dict | None = None,
    latest_success_record: dict | None = None,
    health_snapshot: dict | None = None,
    latest_dry_run: dict | None = None,
) -> dict[str, Any]:
    run_summary = run_summary or {}
    task_state = task_state or {}
    task_validation = task_validation or {}
    channels_map = channels_data.get("channels", {}) if isinstance(channels_data, dict) else {}

    if not selected_task_id or not isinstance(selected_task, dict):
        return {
            "selected_task_id": selected_task_id,
            "can_run": False,
            "run_reasons": ["未选择任务"],
            "can_send": False,
            "send_reasons": ["未选择任务"],
            "can_archive": False,
            "archive_reasons": ["未选择任务"],
            "route_checks": [],
            "has_health_snapshot": False,
            "health_reason": "未选择任务",
            "run_status_hint": "请先选择任务。",
            "last_send_hint": "无可参考。",
            "no_push_hint": "无可参考。",
        }

    route_checks: list[dict[str, Any]] = []
    routes = normalize_channel_routes(selected_task.get("channels"), channels_data)
    has_enabled_send_route = False
    has_enabled_archive_route = False
    send_block_reasons: list[str] = []
    archive_block_reasons: list[str] = []

    for route in routes:
        channel_id = route.get("channel_id", "")
        channel_def = channels_map.get(channel_id, {}) if isinstance(channels_map, dict) else {}
        route_record = {
            "channel_id": channel_id,
            "audience": route.get("audience", ""),
            "purpose": route.get("purpose", "default"),
            "enabled": bool(route.get("enabled", True)),
        }
        if not channel_def:
            route_record.update(
                {
                    "is_found": False,
                    "is_ready": False,
                    "is_archive": False,
                    "name": channel_id or "未命名频道",
                    "reason": "频道不存在，请先在频道管理补齐定义。",
                    "kind": "missing_channel",
                }
            )
            send_block_reasons.append(f"路由 {channel_id or '未知'} 不存在")
            archive_block_reasons.append(f"路由 {channel_id or '未知'} 不存在")
            route_checks.append(route_record)
            continue

        validation = validate_channel_definition(channel_id, channel_def)
        channel_type = channel_def.get("type", "wecom")
        is_archive = channel_type == "web_archive"
        is_ready = bool(validation.get("is_ready", False))

        route_record.update(
            {
                "is_found": True,
                "is_ready": is_ready,
                "is_archive": is_archive,
                "name": str(channel_def.get("name") or channel_id),
                "type": channel_type,
                "reason": "待发送可行性核验" if is_ready else "频道配置不完整",
            }
        )

        if is_ready:
            if is_archive:
                has_enabled_archive_route = True
            else:
                has_enabled_send_route = True
        elif is_archive:
            archive_block_reasons.append(f"{channel_id}（{channel_def.get('name', channel_id)}）配置不完整")
        else:
            send_block_reasons.append(f"{channel_id}（{channel_def.get('name', channel_id)}）配置不完整")

        route_checks.append(route_record)

    validation_issues = task_validation.get("issues") or []
    has_validation_error = not task_validation.get("is_runnable", False)
    needs_revalidation = bool(task_state.get("needs_revalidation"))
    is_enabled = bool(selected_task.get("enabled", False))
    schedule = _safe_get_task_schedule(selected_task)
    schedule_ready = ("hour" in schedule and "minute" in schedule)
    run_blockers: list[str] = []
    if not is_enabled:
        run_blockers.append("任务未启用（enabled=False），不会触发定时运行")
    if not schedule_ready:
        run_blockers.append("调度配置不完整，无法按时运行")
    if has_validation_error:
        run_blockers.extend(
            [
                issue.get("message", "配置缺口")
                for issue in validation_issues
                if isinstance(issue, dict) and issue.get("level") == "error"
            ][:3]
        )
    if needs_revalidation:
        run_blockers.append("任务配置变更后未重新预检，建议先执行一轮预检")

    if not routes:
        run_blockers.append("尚未绑定任何频道")
        send_block_reasons.append("未绑定任何频道")

    can_run = is_enabled and schedule_ready and not has_validation_error and not needs_revalidation
    can_send = can_run and bool(has_enabled_send_route)
    can_archive = can_run and bool(has_enabled_archive_route)

    if not run_blockers:
        if can_run:
            run_status_hint = "当前配置满足运行条件（满足定时触发与必填项）。"
        else:
            run_status_hint = "运行条件不足。"
    else:
        run_status_hint = "；".join(run_blockers)

    if can_send:
        send_hint = "至少有一个可执行发送频道；任务在 dry run 通过后可尝试发送。"
    elif not routes:
        send_hint = "未配置任何发送/归档路由。"
    elif any(not route.get("is_archive") for route in route_checks):
        send_hint = "发送频道存在但当前配置不完整，需补齐后才能发送。"
    else:
        send_hint = "无发送类路由（可能为仅归档任务）。"

    if can_archive:
        archive_hint = "存在可用 web_archive 路由：运行后会沉淀任务内容。"
    else:
        archive_hint = "未命中 web_archive 路由，默认不会写入 Web 存档。"

    health_reason = "已有健康快照"
    if not health_snapshot:
        health_reason = "尚未刷新 RSS 健康快照，请先补齐源并点刷新。"
    elif health_snapshot.get("is_stale"):
        health_reason = "健康快照已过期，建议先刷新后再判断。"

    latest_run_status = "无最近运行"
    if latest_run_record:
        latest_run_status = f"最近运行：{'已运行' if latest_run_record.get('ok') else '运行失败'}（{latest_run_record.get('started_at', '—')}）"

    latest_send_status = "无成功发送记录"
    if latest_success_record:
        latest_send_status = f"最近成功发送：{latest_success_record.get('started_at', '—')}"

    dry_run_status = "未执行"
    if latest_dry_run:
        if latest_dry_run.get("ok"):
            dry_run_status = "Dry Run 正常（当前可用于预检）"
        else:
            dry_run_status = f"Dry Run 失败：{latest_dry_run.get('error', '未知错误')}"

    return {
        "selected_task_id": selected_task_id,
        "can_run": can_run,
        "run_reasons": run_blockers,
        "run_status_hint": run_status_hint,
        "latest_run_status": latest_run_status,
        "latest_send_status": latest_send_status,
        "can_send": can_send,
        "send_reasons": send_block_reasons,
        "send_hint": send_hint,
        "can_archive": can_archive,
        "archive_reasons": archive_block_reasons,
        "archive_hint": archive_hint,
        "route_checks": route_checks,
        "has_health_snapshot": bool(health_snapshot),
        "health_reason": health_reason,
        "no_push_hint": _build_no_push_hint(run_summary=run_summary),
        "dry_run_status": dry_run_status,
    }


def render_execution_precheck_card(readiness: dict[str, Any]) -> dict[str, Any]:
    st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
    st.markdown('<div class="ib-section-title">执行预检结果</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ib-section-copy">该模块给出本次运行前的可执行性预判：是否会按配置运行、是否会发送、是否会写入 Web Archive。</div>',
        unsafe_allow_html=True,
    )

    col_run, col_send, col_archive = st.columns(3)
    with col_run:
        _render_readiness_chip(
            "会不会运行",
            "ok" if readiness["can_run"] else "error",
            readiness.get("run_status_hint", "—"),
        )
    with col_send:
        _render_readiness_chip(
            "会不会发送",
            "ok" if readiness["can_send"] else ("warn" if readiness.get("can_run") else "error"),
            readiness.get("send_hint", "—"),
        )
    with col_archive:
        _render_readiness_chip(
            "会不会归档",
            "ok" if readiness["can_archive"] else ("warn" if readiness.get("can_run") else "error"),
            readiness.get("archive_hint", "—"),
        )

    st.markdown("#### 最近运行与调试参考")
    st.caption(f"{readiness.get('latest_run_status', '无最近运行')} | {readiness.get('latest_send_status', '无发送记录')}")
    st.caption(f"{readiness.get('dry_run_status', '未执行')} | 健康快照：{readiness.get('health_reason', '—')}")
    st.caption(f"No Push 诊断提示：{readiness.get('no_push_hint', '无历史结果')}")


    if readiness["route_checks"]:
        with st.expander("路由可执行性细则", expanded=False):
            for route in readiness["route_checks"]:
                st.markdown(
                    f"- {route.get('name', route.get('channel_id'))}（{route.get('type', '未知')}）"
                    f" | 受众：{route.get('audience') or '—'} | 用途：{route.get('purpose') or 'default'}"
                    f" | { '可用' if route.get('is_ready') else '不可用' }"
                )
                if route.get("reason"):
                    st.caption(route.get("reason", ""))

    st.markdown("</div>", unsafe_allow_html=True)
    return readiness


def _command_result_to_ui_result(command_result) -> dict:
    payload = dict(command_result.run_result or {})
    task_version = command_result.task_version.to_dict() if command_result.task_version else None
    run_trace = command_result.run_trace.to_dict() if command_result.run_trace else None
    diagnosis = command_result.diagnosis.to_dict() if command_result.diagnosis else None
    payload.update(
        {
            "ok": command_result.ok,
            "error": command_result.error,
            "_domain_command": command_result.command,
            "_task_spec": command_result.task_spec.to_dict() if command_result.task_spec else None,
            "_task_version": task_version,
            "_run_trace": run_trace,
            "_diagnosis": diagnosis,
        }
    )
    return payload


def _build_stage_actions(summary: dict) -> list[str]:
    actions: list[str] = []
    if summary["global_candidates"] == 0:
        actions.append("没有抓到候选内容。先检查 RSS 健康度和搜索配置。")
    elif summary["screened_candidates"] == 0:
        actions.append("AI 初筛没有保留内容。可能是今日确实无重要资讯，或全局筛选标准过严。")
    if summary["unassigned_candidates"] > 0:
        actions.append(f"{summary['unassigned_candidates']} 条内容未分配到板块。建议检查板块说明或信源默认栏目。")
    empty_sections = [
        name for name, count in summary.get("selected_by_category", {}).items()
        if count == 0
    ]
    if empty_sections:
        actions.append("这些板块最终为空：" + "、".join(empty_sections) + "。可检查板块 prompt 或信源覆盖。")
    return actions


def _render_stage_summary(stage_summary: dict) -> None:
    st.markdown("#### 四阶段结果")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("抓到候选", stage_summary["global_candidates"])
    col2.metric("AI 初筛通过", stage_summary["screened_candidates"])
    col3.metric("未分配", stage_summary["unassigned_candidates"])
    col4.metric("最终产出", sum(stage_summary.get("selected_by_category", {}).values()))

    assigned = stage_summary.get("assigned_by_category", {})
    selected = stage_summary.get("selected_by_category", {})
    if assigned or selected:
        st.markdown("#### 板块产出")
        rows = []
        all_sections = list(dict.fromkeys([*assigned.keys(), *selected.keys()]))
        for section in all_sections:
            rows.append(
                {
                    "板块": section,
                    "分配候选": assigned.get(section, 0),
                    "最终产出": selected.get(section, 0),
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)

    actions = _build_stage_actions(stage_summary)
    if actions:
        st.markdown("#### 建议处理")
        for action in actions:
            st.warning(action)
    else:
        st.success("四阶段链路看起来正常，可以根据预览判断是否正式运行。")


def _render_domain_diagnosis(diagnosis: dict | None) -> None:
    if not diagnosis:
        return
    findings = diagnosis.get("findings", []) or []
    if not findings:
        st.success("Domain Diagnosis：未发现明显问题。")
        return

    st.markdown("#### 结构化诊断")
    for finding in findings:
        severity = finding.get("severity", "info")
        message = finding.get("message", "")
        finding_type = finding.get("type", "unknown")
        line = f"`{finding_type}`：{message}"
        if severity == "error":
            st.error(line)
        elif severity == "warning":
            st.warning(line)
        else:
            st.info(line)


def _render_run_trace(run_trace: dict | None) -> None:
    if not run_trace:
        return
    rows = []
    for stage in run_trace.get("stages", []) or []:
        rows.append(
            {
                "阶段": stage.get("stage"),
                "输入": stage.get("input_count", 0),
                "输出": stage.get("output_count", 0),
                "警告": len(stage.get("warnings", []) or []),
                "错误": len(stage.get("errors", []) or []),
            }
        )
    if rows:
        st.markdown("#### RunTrace")
        st.dataframe(rows, use_container_width=True, hide_index=True)


def render_task_run_result(
    result: dict,
    *,
    summarize_task_debug_result,
    expanded: bool = False,
    title_prefix: str = "运行",
) -> None:
    result_task_id = result.get("_selected_task_id") or result.get("task_id")
    result_task_name = result.get("_selected_task_name", result_task_id)
    task_version = result.get("_task_version") or {}
    dry_run = bool(result.get("dry_run"))
    st.markdown(
        f'<div class="ib-chip-row"><span class="ib-chip ib-chip-neutral">{title_prefix}任务: {result_task_name}</span>'
        f'<span class="ib-chip ib-chip-neutral">任务 ID: {result_task_id}</span>'
        f'<span class="ib-chip ib-chip-neutral">版本: {task_version.get("version_id", "legacy")}</span></div>',
        unsafe_allow_html=True,
    )
    if result.get("ok"):
        action_label = "Dry Run 完成" if dry_run else "正式运行完成"
        st.success(f"✅ {action_label}（pipeline: {result.get('pipeline')}）")
    else:
        action_label = "Dry Run 失败" if dry_run else "正式运行失败"
        st.error(f"❌ {action_label}: {result.get('error', '未知错误')}")

    stage_summary = summarize_task_debug_result(result)
    _render_stage_summary(stage_summary)
    _render_domain_diagnosis(result.get("_diagnosis"))
    _render_run_trace(result.get("_run_trace"))

    if result.get("final_markdown"):
        st.markdown("#### 📤 简报预览")
        st.markdown(result["final_markdown"])

    with st.expander("开发者详情：完整中间结果", expanded=expanded):
        st.json({
            "ok": result.get("ok"),
            "pipeline": result.get("pipeline"),
            "dry_run": result.get("dry_run"),
            "task_id": result.get("task_id"),
            "task_name": result_task_name,
            "error": result.get("error"),
            "channel_results": result.get("channel_results", []),
            "task_version": result.get("_task_version"),
            "diagnosis": result.get("_diagnosis"),
        }, expanded=False)
        if result.get("_run_trace"):
            st.markdown("#### run_trace")
            st.json(result.get("_run_trace"), expanded=False)
        st.markdown("#### stage_results")
        st.json(result.get("stage_results", {}), expanded=False)


def render_dry_run_result(result: dict, *, summarize_task_debug_result, expanded: bool = False) -> None:
    render_task_run_result(
        result,
        summarize_task_debug_result=summarize_task_debug_result,
        expanded=expanded,
        title_prefix="Dry Run ",
    )


def run_dry_run_task(*, scheduler, task_id: str, task_def: dict, state_key: str) -> None:
    with st.spinner(f"正在 Dry Run 任务「{task_id}」..."):
        try:
            if hasattr(scheduler, "dry_run_task_command"):
                result = _command_result_to_ui_result(scheduler.dry_run_task_command(task_id))
            else:
                result = scheduler.run_task_by_id(task_id, dry_run=True)
        except Exception as e:
            result = {"ok": False, "error": str(e)}
    st.session_state[state_key] = {
        **result,
        "_selected_task_id": task_id,
        "_selected_task_name": task_def.get("name", task_id),
    }


def render_inline_dry_run_panel(
    *,
    selected_task_id: str | None,
    selected_task: dict,
    scheduler,
    summarize_task_debug_result,
    run_enabled: bool = True,
) -> None:
    st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
    st.markdown('<div class="ib-section-title">Dry Run 验证</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ib-section-copy">先跑一次不发送消息的完整链路：抓取、AI 初筛、板块分配、最终成稿。优先看这里判断是否可以正式运行。</div>',
        unsafe_allow_html=True,
    )
    if not selected_task_id:
        st.info("请先选择或创建任务。")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    dry_run_key = f"verification_dry_run::{selected_task_id}"
    if st.button(
        "🔬 在验证页运行 Dry Run",
        type="primary",
        key=f"inline_dry_run_btn::{selected_task_id}",
        use_container_width=True,
        disabled=not run_enabled,
    ):
        run_dry_run_task(
            scheduler=scheduler,
            task_id=selected_task_id,
            task_def=selected_task,
            state_key=dry_run_key,
        )

    result = st.session_state.get(dry_run_key)
    if result:
        render_dry_run_result(result, summarize_task_debug_result=summarize_task_debug_result)
    else:
        st.caption("还没有当前任务的 Dry Run 结果。建议在刷新健康度后跑一次。")
    st.markdown("</div>", unsafe_allow_html=True)


def render_dry_run_tab(*, tasks: dict, selected_task_id: str | None, scheduler, summarize_task_debug_result) -> None:
    st.subheader("验证与运行")
    st.caption("Dry Run 是主验证入口：完整执行但不发送消息。确认预览无误后，再回到总览或任务页正式运行。")

    task_ids = list(tasks.keys())
    if not task_ids:
        st.warning("暂无任务，请先在「📋 任务管理」创建任务。")
        return

    selected = st.selectbox(
        "选择任务",
        options=task_ids,
        index=task_ids.index(selected_task_id) if selected_task_id in task_ids else 0,
    )

    col_run, _col_info = st.columns([1, 3])
    with col_run:
        dry_run = st.button("🔬 Dry Run", type="primary", use_container_width=True)

    task_def = tasks.get(selected, {})
    st.markdown(f"**Pipeline**: `{task_def.get('pipeline', 'editorial')}`")
    st.markdown(f"**频道**: `{', '.join(task_def.get('channels', []))}`")
    sched = task_def.get("schedule", {})
    st.markdown(f"**调度**: {sched.get('hour', 8):02d}:{sched.get('minute', 0):02d}")

    if dry_run:
        run_dry_run_task(
            scheduler=scheduler,
            task_id=selected,
            task_def=task_def,
            state_key="task_debug_result",
        )

    if "task_debug_result" not in st.session_state:
        return

    result = st.session_state["task_debug_result"]
    result_task_id = result.get("_selected_task_id")
    result_task_name = result.get("_selected_task_name", result_task_id)
    if result_task_id == selected:
        render_dry_run_result(result, summarize_task_debug_result=summarize_task_debug_result)
    else:
        st.info(f"当前保存的是任务「{result_task_name}」的 Dry Run 结果；切回对应任务可查看详情。")
