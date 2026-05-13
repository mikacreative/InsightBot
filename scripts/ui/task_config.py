from __future__ import annotations

from copy import deepcopy

import streamlit as st


def get_missing_setup_steps(task_def: dict, validation_result: dict) -> list[str]:
    summary = validation_result.get("summary", {}) if validation_result else {}
    steps: list[str] = []
    if summary.get("section_count", 0) == 0:
        steps.append("添加至少一个栏目")
    if summary.get("rss_source_count", 0) == 0:
        steps.append("添加至少一个 RSS 信源")
    if not task_def.get("channels"):
        steps.append("选择至少一个推送频道")
    if not task_def.get("schedule"):
        steps.append("设置自动运行时间")
    return steps


def render_task_empty_state_wizard(
    *,
    task_id: str,
    task_def: dict,
    validation_result: dict,
    channels_data: dict,
    save_task_definition,
    defaults: dict,
) -> None:
    missing_steps = get_missing_setup_steps(task_def, validation_result)
    if not missing_steps:
        return

    st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
    st.markdown('<div class="ib-section-title">最小可运行配置向导</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ib-section-copy">这个任务还没到可运行状态。先补齐栏目、信源、频道和调度，保存后再进入健康检查与 Dry Run。</div>',
        unsafe_allow_html=True,
    )
    st.warning("待补齐：" + " / ".join(missing_steps))

    channels = channels_data.get("channels", {})
    channel_options = list(channels.keys())
    with st.form(f"task_setup_wizard::{task_id}"):
        col1, col2 = st.columns([1.1, 1.4])
        with col1:
            category_name = st.text_input(
                "首个栏目名称",
                value=next(iter(task_def.get("sections", {}) or {}), ""),
                placeholder="例如：品牌营销动态",
            ).strip()
            rss_text = st.text_area(
                "RSS 源（每行一个）",
                value="",
                height=120,
                placeholder="https://example.com/feed.xml",
            )
        with col2:
            selected_channels = st.multiselect(
                "推送频道",
                options=channel_options,
                default=[ch for ch in task_def.get("channels", []) if ch in channel_options],
            )
            sched = task_def.get("schedule", {}) or {}
            hour_col, min_col = st.columns(2)
            with hour_col:
                schedule_hour = st.number_input("小时", min_value=0, max_value=23, value=int(sched.get("hour", 8)))
            with min_col:
                schedule_minute = st.number_input("分钟", min_value=0, max_value=59, value=int(sched.get("minute", 0)))
            enabled = st.checkbox("保存后启用任务", value=bool(task_def.get("enabled", False)))

        submitted = st.form_submit_button("保存最小配置", use_container_width=True)

    if not submitted:
        st.markdown("</div>", unsafe_allow_html=True)
        return

    if not category_name:
        st.error("请先填写栏目名称。")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    rss_items = [line.strip() for line in rss_text.splitlines() if line.strip()]
    existing_rss = [
        item.get("url", "").strip()
        for item in (task_def.get("sources", {}) or {}).get("rss", [])
        if isinstance(item, dict)
    ]
    if not rss_items and not existing_rss:
        st.error("请至少填写一个 RSS 源。")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    if not selected_channels:
        st.error("请至少选择一个推送频道。")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    updated_task = deepcopy(task_def)
    updated_task["enabled"] = enabled
    updated_task["channels"] = selected_channels
    updated_task["schedule"] = {"hour": int(schedule_hour), "minute": int(schedule_minute)}
    updated_task.setdefault("pipeline", "editorial")
    updated_task.setdefault("pipeline_config", deepcopy(defaults))
    sources = updated_task.setdefault("sources", {})
    sections = updated_task.setdefault("sections", {})
    rss_sources = list(sources.get("rss", []) or [])
    existing_urls = {
        item.get("url", "").strip()
        for item in rss_sources
        if isinstance(item, dict)
    }
    for rss in rss_items:
        if rss in existing_urls:
            continue
        rss_sources.append(
            {
                "id": f"source_{len(rss_sources) + 1}",
                "url": rss,
                "enabled": True,
                "tags": [category_name],
                "section_hints": [category_name],
            }
        )
        existing_urls.add(rss)
    sources["rss"] = rss_sources
    sources.setdefault("search", {"enabled": False, "provider": "baidu", "queries": []})
    sections.setdefault(
        category_name,
        {"prompt": "", "keywords": [], "source_hints": [category_name]},
    )

    save_task_definition(task_id, updated_task)
    st.success("最小可运行配置已保存。")
    st.rerun()
