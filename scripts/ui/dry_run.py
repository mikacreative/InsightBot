from __future__ import annotations

import streamlit as st


def render_dry_run_result(result: dict, *, summarize_task_debug_result, expanded: bool = False) -> None:
    result_task_id = result.get("_selected_task_id") or result.get("task_id")
    result_task_name = result.get("_selected_task_name", result_task_id)
    st.markdown(
        f'<div class="ib-chip-row"><span class="ib-chip ib-chip-neutral">Dry Run 任务: {result_task_name}</span>'
        f'<span class="ib-chip ib-chip-neutral">任务 ID: {result_task_id}</span></div>',
        unsafe_allow_html=True,
    )
    if result.get("ok"):
        st.success(f"✅ Dry Run 完成（pipeline: {result.get('pipeline')}）")
    else:
        st.error(f"❌ Dry Run 失败: {result.get('error', '未知错误')}")

    if result.get("final_markdown"):
        st.markdown("#### 📤 简报预览")
        st.markdown(result["final_markdown"])

    with st.expander("🔬 完整中间结果", expanded=expanded):
        st.json({
            "ok": result.get("ok"),
            "pipeline": result.get("pipeline"),
            "dry_run": result.get("dry_run"),
            "task_id": result.get("task_id"),
            "task_name": result_task_name,
            "error": result.get("error"),
            "channel_results": result.get("channel_results", []),
        }, expanded=False)
        stage_summary = summarize_task_debug_result(result)
        st.markdown("#### 流程摘要")
        metric_col1, metric_col2, metric_col3 = st.columns(3)
        metric_col1.metric("全局候选", stage_summary["global_candidates"])
        metric_col2.metric("全局初筛通过", stage_summary["screened_candidates"])
        metric_col3.metric("未分配", stage_summary["unassigned_candidates"])

        if stage_summary["assigned_by_category"]:
            st.markdown("#### 板块分配")
            st.json(stage_summary["assigned_by_category"], expanded=False)

        if stage_summary["selected_by_category"]:
            st.markdown("#### 最终产出")
            st.json(stage_summary["selected_by_category"], expanded=False)

        st.markdown("#### stage_results")
        st.json(result.get("stage_results", {}), expanded=False)


def run_dry_run_task(*, scheduler, task_id: str, task_def: dict, state_key: str) -> None:
    with st.spinner(f"正在 Dry Run 任务「{task_id}」..."):
        try:
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
        '<div class="ib-section-copy">在当前验证页直接生成一次不发送消息的完整运行结果，用来衔接健康检查、No Push Diagnosis 和板块调试。</div>',
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
    st.subheader("🔬 任务调试")
    st.caption("选择任务并运行 Dry Run — 仅在面板展示结果，不发送任何频道消息。")

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
