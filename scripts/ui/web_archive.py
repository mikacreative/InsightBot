from __future__ import annotations

import streamlit as st
from datetime import date, datetime

from insightbot.audit_log import append_audit_event
from insightbot.subscribers import resolve_subscriber
from insightbot.web_archive import (
    find_archive_record_index,
    list_archive_records,
    update_archive_record_publication,
)


def _extract_record_date(created_at: object) -> date | None:
    if not created_at:
        return None
    raw = str(created_at).replace("Z", "+00:00").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        return None


def _format_meta(record: dict) -> str:
    parts = [
        record.get("created_at", ""),
        f"任务：{record.get('task_name') or record.get('task_id', '')}",
        f"频道：{record.get('channel_id', '')}",
    ]
    if record.get("audience"):
        parts.append(f"对象：{record['audience']}")
    if record.get("purpose") and record.get("purpose") != "default":
        parts.append(f"用途：{record['purpose']}")
    return " | ".join([item for item in parts if item])


def _query_record_id() -> str:
    return _query_param("record_id")


def _query_param(name: str) -> str:
    try:
        value = st.query_params.get(name, "")
    except Exception:
        value = ""
    if isinstance(value, list):
        return str(value[0]).strip() if value else ""
    return str(value).strip()


def render_web_archive_page(
    *,
    bot_dir: str,
    public_mode: bool = False,
    can_manage_publication: bool = False,
    actor: dict | None = None,
) -> None:
    actor = actor or {}
    if public_mode:
        st.title("InsightBot Briefing")
        st.caption("订阅资讯存档")
        subscriber = resolve_subscriber(_query_param("token"), bot_dir=bot_dir)
        st.caption(f"当前访问范围：{subscriber['name']}")
        records = list_archive_records(
            bot_dir=bot_dir,
            audiences=subscriber.get("audiences", ["public"]),
            limit=200,
        )
    else:
        st.subheader("订阅者页面")
        st.caption("这里展示通过 web_archive 频道沉淀的任务资讯，可按任务和频道回溯历史内容。")
        records = list_archive_records(bot_dir=bot_dir, include_unpublished=True, limit=200)
    task_options = ["全部"] + sorted(
        {
            str(item.get("task_id", "")).strip()
            for item in records
            if str(item.get("task_id", "")).strip()
        }
    )
    channel_options = ["全部"] + sorted(
        {
            str(item.get("channel_id", "")).strip()
            for item in records
            if str(item.get("channel_id", "")).strip()
        }
    )

    date_values = []
    for item in records:
        record_date = _extract_record_date(item.get("created_at"))
        if record_date:
            date_values.append(record_date)

    if not records:
        st.info("暂时还没有 Web 存档。给任务添加 web_archive 频道并运行后，这里会出现可浏览记录。")
        return

    date_min = min(date_values) if date_values else date.today()
    date_max = max(date_values) if date_values else date.today()
    start_date = date_min
    end_date = date_max

    audience_values = sorted(
        {
            audience
            for item in records
            for audience in (item.get("audiences") or [])
            if isinstance(audience, str) and audience.strip()
        }
    )
    audience_options = ["全部"] + audience_values

    query_record_id = _query_record_id()
    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        selected_task = st.selectbox("任务", options=task_options)
    with filter_col2:
        selected_channel = st.selectbox("频道", options=channel_options)
    if date_min != date_max:
        _, filter_col3, filter_col4 = st.columns([1, 1, 1])
        with filter_col3:
            start_date = st.date_input("起始日期", value=date_min, min_value=date_min, max_value=date_max)
        with filter_col4:
            end_date = st.date_input("结束日期", value=date_max, min_value=date_min, max_value=date_max)

    filtered = records
    if selected_task != "全部":
        filtered = [item for item in filtered if item.get("task_id") == selected_task]
    if selected_channel != "全部":
        filtered = [item for item in filtered if item.get("channel_id") == selected_channel]
    if audience_options:
        with st.expander("受众筛选", expanded=False):
            selected_audience = st.selectbox("受众", options=audience_options, index=0)
    else:
        selected_audience = "全部"

    if start_date and end_date and start_date > end_date:
        start_date, end_date = end_date, start_date

    filtered = [
        item
        for item in filtered
        if (
            not start_date
            or (
                (item_created_at := _extract_record_date(item.get("created_at"))) is not None
                and item_created_at <= end_date
                and item_created_at >= start_date
            )
        )
    ]
    if selected_audience != "全部":
        filtered = [item for item in filtered if selected_audience in set((item.get("audiences") or []))]

    if not filtered:
        st.warning("当前筛选条件下没有存档。")
        return

    selected_index = st.selectbox(
        "历史记录",
        options=list(range(len(filtered))),
        index=find_archive_record_index(filtered, query_record_id),
        format_func=lambda idx: f"{filtered[idx].get('created_at', '')} · {filtered[idx].get('title') or filtered[idx].get('task_name') or filtered[idx].get('task_id')}",
    )
    record = filtered[selected_index]

    metric_col1, metric_col2, metric_col3 = st.columns(3)
    with metric_col1:
        st.metric("候选", str(record.get("candidate_count", 0)))
    with metric_col2:
        st.metric("入选", str(record.get("selected_count", 0)))
    with metric_col3:
        st.metric("发布", record.get("publication_status", "published"))

    st.caption(_format_meta(record))
    st.code(str(record.get("record_id", "")), language=None)

    if not public_mode and can_manage_publication:
        control_col1, control_col2, control_col3 = st.columns([1, 1, 2])
        with control_col1:
            next_status = st.selectbox(
                "发布状态",
                options=["published", "draft", "unpublished"],
                index=["published", "draft", "unpublished"].index(
                    record.get("publication_status", "published")
                    if record.get("publication_status", "published") in {"published", "draft", "unpublished"}
                    else "published"
                ),
                key=f"archive_status::{record.get('record_id')}",
            )
        with control_col2:
            next_visibility = st.selectbox(
                "可见性",
                options=["audience", "public"],
                index=0 if record.get("visibility", "audience") == "audience" else 1,
                key=f"archive_visibility::{record.get('record_id')}",
            )
        with control_col3:
            next_audiences_text = st.text_input(
                "可见受众",
                value=", ".join(record.get("audiences", []) or []),
                key=f"archive_audiences::{record.get('record_id')}",
            )
        if st.button("保存发布设置", key=f"archive_save::{record.get('record_id')}"):
            next_audiences = [
                item.strip()
                for item in next_audiences_text.replace("，", ",").split(",")
                if item.strip()
            ]
            ok = update_archive_record_publication(
                str(record.get("record_id", "")),
                bot_dir=bot_dir,
                publication_status=next_status,
                visibility=next_visibility,
                audiences=next_audiences,
            )
            if ok:
                append_audit_event(
                    bot_dir,
                    actor=actor,
                    action="archive.publication.update",
                    target={"type": "archive_record", "id": str(record.get("record_id", ""))},
                    changes={
                        "publication_status": next_status,
                        "visibility": next_visibility,
                        "audiences": next_audiences,
                    },
                )
                st.success("发布设置已保存。")
                st.rerun()
            else:
                st.error("没有找到这条存档记录。")
    elif not public_mode:
        st.info("当前角色只能查看存档，不能修改发布状态。")

    if record.get("title"):
        st.markdown(f"## {record['title']}")
    st.markdown(record.get("markdown") or "暂无正文。")

    if not public_mode:
        with st.expander("存档元数据"):
            st.json(
                {
                    key: value
                    for key, value in record.items()
                    if key != "markdown"
                }
            )
