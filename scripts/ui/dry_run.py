from __future__ import annotations

import streamlit as st


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
    if st.button("🔬 在验证页运行 Dry Run", type="primary", key=f"inline_dry_run_btn::{selected_task_id}", use_container_width=True):
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
