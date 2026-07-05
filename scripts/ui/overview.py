from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import streamlit as st


def _safe_get_task_feeds(selected_task: dict) -> dict:
    return dict(selected_task.get("feeds", {})) if isinstance(selected_task, dict) else {}


def _safe_dump_dict(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=False, indent=2)
    except TypeError:
        return json.dumps(str(data), ensure_ascii=False, indent=2)


def _build_task_summary(task: dict) -> dict[str, int | str | bool]:
    if not isinstance(task, dict):
        task = {}
    task_channels = task.get("channels", []) or []
    if isinstance(task_channels, list):
        channel_count = len(task_channels)
    elif isinstance(task_channels, dict):
        channel_count = len(task_channels)
    else:
        channel_count = 0
    feed_count = 0
    feeds = _safe_get_task_feeds(task)
    for feed in feeds.values():
        feed_count += len(feed.get("rss", [])) if isinstance(feed, dict) else 0
    return {
        "boards": len(feeds),
        "feeds": feed_count,
        "channels": channel_count,
        "pipeline": task.get("pipeline", "editorial"),
        "search_enabled": bool((task.get("search", {}) or {}).get("enabled", False)),
    }


def _diff_raw_vs_effective_task_config(raw_task: dict, effective_task: dict) -> list[str]:
    raw_task = raw_task or {}
    effective_task = effective_task or {}
    notes: list[str] = []

    raw_feeds = _safe_get_task_feeds(raw_task)
    effective_feeds = _safe_get_task_feeds(effective_task)
    missing_raw_feeds = sorted(set(effective_feeds) - set(raw_feeds))
    if missing_raw_feeds:
        notes.append("运行时注入了额外板块（未在任务 JSON 显式定义）：" + "、".join(missing_raw_feeds))

    raw_channels = set(raw_task.get("channels", []) or [])
    effective_channels = set(effective_task.get("channels", []) or [])
    if not raw_task.get("channels") and effective_channels:
        notes.append("运行时注入了默认频道清单（raw 配置未显式指定）。")
    if raw_channels != effective_channels and raw_task.get("channels") and effective_channels:
        added = sorted(effective_channels - raw_channels)
        removed = sorted(raw_channels - effective_channels)
        if added:
            notes.append("运行时补齐新增了频道："
                         + "、".join(added))
        if removed:
            notes.append("运行时移除了以下频道："
                         + "、".join(removed))

    raw_queries = (raw_task.get("search", {}) or {}).get("queries", []) or []
    effective_queries = (effective_task.get("search", {}) or {}).get("queries", []) or []
    if not raw_queries and effective_queries:
        notes.append("运行时使用了基础配置中的搜索参数（raw 配置未显式定义 search）。")

    raw_pipeline = raw_task.get("pipeline", None)
    effective_pipeline = effective_task.get("pipeline", "editorial")
    if raw_pipeline != effective_pipeline:
        notes.append(f"pipeline 发生回退/覆盖：raw={raw_pipeline or '未设置'}，effective={effective_pipeline}")

    return notes


def render_task_overview(
    *,
    selected_task_id: str | None,
    selected_task: dict,
    selected_effective_task: dict,
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
    workspace_state: dict | None = None,
) -> None:
    workspace_state = workspace_state or {}
    task_card = workspace_state.get("selected_task_card") or {}
    source_health = workspace_state.get("selected_source_health") or {}
    shared_diagnosis = workspace_state.get("human_diagnosis") or {}
    validation_summary = selected_task_validation.get("summary", {}) if selected_task_validation else {}
    section_count = validation_summary.get("section_count", validation_summary.get("category_count", 0))
    rss_source_count = validation_summary.get("rss_source_count", validation_summary.get("feed_count", 0))

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
    shared_status = task_card.get("status") or task_state_label
    shared_status_reason = task_card.get("status_reason") or task_state_copy
    shared_source_errors = source_health.get("error_count", health_counts.get("error", 0))
    st.markdown(
        f"""
        <div class="ib-kpi-grid">
          <div class="ib-kpi-card">
            <div class="ib-kpi-label">任务状态</div>
            <div class="ib-kpi-value" style="font-size:1.05rem;">{shared_status}</div>
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

    selected_task_raw_summary = _build_task_summary(selected_task)
    selected_task_effective_summary = _build_task_summary(selected_task_effective)
    config_deltas = _diff_raw_vs_effective_task_config(selected_task, selected_effective_task)

    top_col1, top_col2 = st.columns([1.35, 1.0])
    with top_col1:
        st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
        st.markdown('<div class="ib-section-title">任务状态</div>', unsafe_allow_html=True)
        render_operating_chip(shared_status, task_state_class)
        st.markdown(
            f"""
            <div class="ib-section-copy">
              {shared_status_reason}<br/>
              {shared_diagnosis.get('message', '')}<br/>
              板块数：{section_count}<br/>
              RSS 源数：{rss_source_count}<br/>
              异常 RSS 源：{shared_source_errors}<br/>
              最近运行结果：{run_metrics.get('result_label', '未知')}
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
    st.markdown('<div class="ib-section-title">Raw / Effective 配置语义</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ib-section-copy">Raw（编辑态）是控制台当前保存内容；Effective（执行态）为运行时实际生效内容。对照可帮助你确认是否有回退/补齐。</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="ib-kpi-grid">
          <div class="ib-kpi-card">
            <div class="ib-kpi-label">Raw 板块 / RSS</div>
            <div class="ib-kpi-value" style="font-size:1.05rem;">{selected_task_raw_summary['boards']} / {selected_task_raw_summary['feeds']}</div>
          </div>
          <div class="ib-kpi-card">
            <div class="ib-kpi-label">Effective 板块 / RSS</div>
            <div class="ib-kpi-value" style="font-size:1.05rem;">{selected_task_effective_summary['boards']} / {selected_task_effective_summary['feeds']}</div>
          </div>
          <div class="ib-kpi-card">
            <div class="ib-kpi-label">Raw 频道数</div>
            <div class="ib-kpi-value" style="font-size:1.05rem;">{selected_task_raw_summary['channels']}</div>
          </div>
          <div class="ib-kpi-card">
            <div class="ib-kpi-label">Effective 频道数</div>
            <div class="ib-kpi-value" style="font-size:1.05rem;">{selected_task_effective_summary['channels']}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if config_deltas:
        for item in config_deltas:
            st.warning(item)
    else:
        st.success("Raw 与 Effective 在关键字段上保持一致。")

    snapshot_payload = {
        "snapshot_at": datetime.now().isoformat(timespec="seconds"),
        "task_id": selected_task_id,
        "raw_task": selected_task,
        "effective_task": selected_effective_task,
    }
    st.download_button(
        "📸 生成本地配置快照（JSON）",
        data=_safe_dump_dict(snapshot_payload),
        file_name=f"{selected_task_id or 'selected-task'}-config-snapshot.json",
        mime="application/json",
        use_container_width=True,
    )
    st.caption("快照仅本地下载，不写入数据库或生产环境；用于排查与回溯。")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
    st.markdown('<div class="ib-section-title">内容源与板块</div>', unsafe_allow_html=True)
    st.markdown('<div class="ib-section-copy">按实际运行口径展示当前任务绑定的板块、RSS 源与关键词。</div>', unsafe_allow_html=True)
    task_feeds = _safe_get_task_feeds(selected_effective_task)
    if not task_feeds:
        st.info("当前任务暂无内容板块。可在「任务管理」中补齐后查看。")
    else:
        for idx, (category_name, feed_cfg) in enumerate(task_feeds.items()):
            feed_cfg = feed_cfg or {}
            rss_items = list(feed_cfg.get("rss", []) or [])
            keywords = list(feed_cfg.get("keywords", []) or [])
            prompt = (feed_cfg.get("prompt", "") or "").strip()
            with st.expander(f"📂 {category_name}", expanded=(idx == 0)):
                st.markdown(
                    f"RSS 数：{len(rss_items)} | 关键词数：{len(keywords)}",
                    unsafe_allow_html=True,
                )
                if rss_items:
                    st.markdown("**RSS 源**")
                    for item in rss_items:
                        st.code(item)
                else:
                    st.caption("尚未配置 RSS 源。")

                if keywords:
                    st.markdown("**关键词**")
                    st.markdown("、".join(keywords))
                else:
                    st.caption("尚未配置关键词。")

                if prompt:
                    st.markdown("**板块筛选 Prompt（摘要）**")
                    st.caption(prompt[:220] + ("..." if len(prompt) > 220 else ""))
                else:
                    st.caption("尚未配置 Prompt。")
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
