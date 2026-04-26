from __future__ import annotations

import streamlit as st


def render_task_overview(
    *,
    selected_task_id: str | None,
    selected_task: dict,
    selected_task_categories: list[str],
    selected_task_validation: dict,
    selected_task_state: dict,
    latest_run_record: dict | None,
    latest_success_record: dict | None,
    health_snapshot: dict | None,
    run_metrics: dict,
    diagnosis_cards: list[dict],
    prompt_history: list[dict],
    task_state_label: str,
    task_state_class: str,
    task_state_copy: str,
    format_timestamp,
    render_operating_chip,
    render_diagnosis_card,
) -> None:
    st.subheader("运营概览")
    active_task_name = selected_task.get("name", selected_task_id) if selected_task_id else "未选择任务"
    st.caption(f"当前聚焦任务：{active_task_name}。优先看最近一次运行、异常摘要和最近调试动作。")
    if selected_task_id:
        st.markdown(
            f'<div class="ib-chip-row"><span class="ib-chip ib-chip-neutral">任务 ID: {selected_task_id}</span>'
            f'<span class="ib-chip ib-chip-neutral">任务名: {active_task_name}</span></div>',
            unsafe_allow_html=True,
        )

    health_counts = (health_snapshot or {}).get("counts", {})
    st.markdown(
        f"""
        <div class="ib-kpi-grid">
          <div class="ib-kpi-card">
            <div class="ib-kpi-label">任务状态</div>
            <div class="ib-kpi-value" style="font-size:1.05rem;">{task_state_label}</div>
          </div>
          <div class="ib-kpi-card">
            <div class="ib-kpi-label">可运行性</div>
            <div class="ib-kpi-value" style="font-size:1.05rem;">{'需重验' if selected_task_state.get('needs_revalidation') else ('可运行' if selected_task_validation.get('is_runnable') else '不可运行')}</div>
          </div>
          <div class="ib-kpi-card">
            <div class="ib-kpi-label">最近一次运行</div>
            <div class="ib-kpi-value" style="font-size:1.05rem;">{format_timestamp((latest_run_record or {}).get('started_at'))}</div>
          </div>
          <div class="ib-kpi-card">
            <div class="ib-kpi-label">最后成功发送</div>
            <div class="ib-kpi-value" style="font-size:1.05rem;">{format_timestamp((latest_success_record or {}).get('started_at'))}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    top_col1, top_col2 = st.columns([1.35, 1.0])
    with top_col1:
        st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
        st.markdown('<div class="ib-section-title">任务状态</div>', unsafe_allow_html=True)
        render_operating_chip(task_state_label, task_state_class)
        st.markdown(
            f"""
            <div class="ib-section-copy">
              {task_state_copy}<br/>
              板块数：{selected_task_validation.get('summary', {}).get('category_count', 0)}<br/>
              RSS 源数：{selected_task_validation.get('summary', {}).get('feed_count', 0)}<br/>
              异常 RSS 源：{health_counts.get('error', 0)}<br/>
              最近运行结果：{run_metrics.get('result_label', '未知')}
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)

    with top_col2:
        st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
        st.markdown('<div class="ib-section-title">最近调试动态</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="ib-section-copy">来自板块调试的最近记录，帮助你判断最近都在调哪些板块。</div>',
            unsafe_allow_html=True,
        )
        if prompt_history:
            for item in prompt_history[:3]:
                mode_label = "草稿试跑" if item.get("mode") == "draft_run" else "当前 vs 草稿"
                item_task = item.get("task_name") or item.get("task_id") or active_task_name
                st.markdown(
                    f"- {item.get('created_at', '')} | {item_task} | {item.get('category', '未命名板块')} | {mode_label} | 草稿状态：{item.get('draft_status', '未知')}"
                )
        else:
            st.info("还没有 Prompt 调试记录。")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
    st.markdown('<div class="ib-section-title">异常摘要</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ib-section-copy">优先展示当前最值得处理的问题。如果要排查“为什么今天没推送”，先看这里。</div>',
        unsafe_allow_html=True,
    )
    if diagnosis_cards:
        for card in diagnosis_cards[:3]:
            render_diagnosis_card(
                card,
                prompt_categories=selected_task_categories,
                key_prefix="overview",
            )
    else:
        st.success("当前没有明显异常摘要，系统状态看起来比较稳定。")
    st.markdown("</div>", unsafe_allow_html=True)
