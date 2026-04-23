import json
import logging
import os
import subprocess
import sys
from copy import deepcopy
from datetime import datetime

import streamlit as st
from insightbot.channels import init_channels, test_channel
from insightbot.config import (
    load_channels,
    load_runtime_config,
    load_tasks,
    load_tasks_config,
    save_channels,
    save_tasks,
)
from insightbot.feed_health import CACHE_TTL_SECONDS, get_feed_health_snapshot, load_health_cache
from insightbot.paths import (
    bot_log_file_path,
    config_content_file_path,
    config_file_path,
    config_secrets_file_path,
    cron_log_file_path,
    default_bot_dir,
    feed_health_cache_file_path,
    task_health_cache_file_path,
)
from insightbot.prompt_debug_history import (
    append_prompt_debug_history,
    load_prompt_debug_history,
    make_compare_record,
    make_draft_run_record,
)
from insightbot.run_history import get_latest_run, get_latest_successful_send
from insightbot.run_diagnosis import build_no_push_diagnosis, parse_recent_run_summary, summarize_recent_run
from insightbot.scheduler import create_scheduler
from insightbot.smart_brief_runner import (
    DEBUG_SAMPLE_NEWS,
    fetch_recent_candidates,
    get_selection_settings,
    run_prompt_debug,
)
from insightbot.task_health_store import clear_task_health, load_task_health, save_task_health
from insightbot.task_runner import run_task
from insightbot.task_state import build_task_revision, load_task_state, touch_revalidation_state
from insightbot.task_validation import validate_task_definition
from insightbot.editorial_pipeline import (
    build_global_candidates,
    screen_global_candidates,
    assign_candidates_to_categories,
    select_for_category,
    run_editorial_pipeline,
)

def main() -> None:
    bot_dir = default_bot_dir()
    content_config_path = config_content_file_path(bot_dir)
    secrets_config_path = config_secrets_file_path(bot_dir)
    legacy_config_path = config_file_path(bot_dir)
    cron_log_path = cron_log_file_path(bot_dir)
    bot_log_path = bot_log_file_path(bot_dir)

    smart_brief_path = os.getenv("SMART_BRIEF_PATH", os.path.join(bot_dir, "smart_brief.py"))
    smart_brief_mode = os.getenv("SMART_BRIEF_MODE", "script").strip().lower()  # script | module

    active_edit_path = content_config_path if os.path.exists(content_config_path) else legacy_config_path

    def load_config() -> dict:
        with open(active_edit_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_runtime_view() -> dict:
        return load_runtime_config(bot_dir)

    def save_config(config: dict) -> None:
        with open(active_edit_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

    def load_secrets_config() -> dict:
        if os.path.exists(secrets_config_path):
            with open(secrets_config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def save_secrets_config(secrets: dict) -> None:
        with open(secrets_config_path, "w", encoding="utf-8") as f:
            json.dump(secrets, f, indent=4, ensure_ascii=False)

    def build_ui_logger() -> logging.Logger:
        logger = logging.getLogger("InsightBot.PromptDebug")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
        return logger

    def set_prompt_debug_category(task_id: str | None, category: str) -> None:
        task_scope = task_id or "default"
        st.session_state[f"prompt_debug_category::{task_scope}"] = category
        draft_key = f"draft_prompt::{task_scope}::{category}"
        if draft_key not in st.session_state:
            st.session_state[draft_key] = selected_task_feeds.get(category, {}).get("prompt", "")

    def seed_prompt_debug_candidates(task_id: str | None, category: str) -> tuple[int, bool]:
        ui_logger = build_ui_logger()
        candidates = fetch_recent_candidates(feed_data=selected_task_feeds.get(category, {}), logger=ui_logger)
        using_fallback = False
        if not candidates:
            candidates = list(DEBUG_SAMPLE_NEWS)
            using_fallback = True
        st.session_state["prompt_debug_candidates"] = candidates
        st.session_state["prompt_debug_meta"] = {
            "category": category,
            "using_fallback": using_fallback,
            "task_id": task_id,
        }
        st.session_state.pop("prompt_debug_result", None)
        st.session_state.pop("prompt_debug_compare", None)
        return len(candidates), using_fallback

    def set_verification_focus(task_id: str | None, category: str | None) -> None:
        task_scope = task_id or "default"
        key = f"verification_focus::{task_scope}"
        if category:
            st.session_state[key] = category
        else:
            st.session_state.pop(key, None)

    def get_verification_focus(task_id: str | None) -> str | None:
        return st.session_state.get(f"verification_focus::{task_id or 'default'}")

    def filter_prompt_history_for_category(items: list[dict], category: str | None) -> list[dict]:
        if not category:
            return items
        scoped = [item for item in items if item.get("category") == category]
        return scoped if scoped else items

    def render_prompt_debug_styles() -> None:
        st.markdown(
            """
            <style>
            .ib-panel {
                border: 1px solid rgba(33, 37, 41, 0.10);
                border-radius: 18px;
                padding: 18px 20px;
                background: linear-gradient(180deg, #ffffff 0%, #f7f3ea 100%);
                box-shadow: 0 8px 24px rgba(55, 41, 18, 0.06);
                margin-bottom: 14px;
            }
            .ib-hero {
                border: 1px solid rgba(26, 54, 93, 0.08);
                border-radius: 22px;
                padding: 20px 22px;
                background: linear-gradient(135deg, #fbf4e8 0%, #eef6f7 100%);
                margin-bottom: 18px;
            }
            .ib-eyebrow {
                font-size: 0.80rem;
                text-transform: uppercase;
                letter-spacing: 0.08em;
                color: #7a5c2e;
                font-weight: 700;
                margin-bottom: 6px;
            }
            .ib-title {
                font-size: 1.45rem;
                font-weight: 800;
                color: #1f2d3d;
                margin-bottom: 8px;
            }
            .ib-subtitle {
                color: #4f5d6b;
                font-size: 0.98rem;
                line-height: 1.55;
            }
            .ib-chip-row {
                display: flex;
                gap: 10px;
                flex-wrap: wrap;
                margin-top: 14px;
            }
            .ib-chip {
                display: inline-flex;
                align-items: center;
                gap: 6px;
                padding: 7px 12px;
                border-radius: 999px;
                font-size: 0.88rem;
                font-weight: 700;
                background: #ffffff;
                color: #2f3e46;
                border: 1px solid rgba(47, 62, 70, 0.10);
            }
            .ib-chip-success {
                background: #eaf8ef;
                color: #1e6b3b;
                border-color: rgba(30, 107, 59, 0.18);
            }
            .ib-chip-warning {
                background: #fff4dd;
                color: #925f00;
                border-color: rgba(146, 95, 0, 0.18);
            }
            .ib-chip-error {
                background: #fdeaea;
                color: #a23030;
                border-color: rgba(162, 48, 48, 0.18);
            }
            .ib-chip-neutral {
                background: #eef3f6;
                color: #415361;
                border-color: rgba(65, 83, 97, 0.16);
            }
            .ib-section-title {
                font-size: 1rem;
                font-weight: 800;
                color: #243746;
                margin-bottom: 4px;
            }
            .ib-section-copy {
                color: #5b6875;
                font-size: 0.92rem;
                line-height: 1.45;
                margin-bottom: 12px;
            }
            .ib-kpi-grid {
                display: grid;
                grid-template-columns: repeat(4, minmax(0, 1fr));
                gap: 12px;
                margin: 14px 0 18px;
            }
            .ib-kpi-card {
                border-radius: 16px;
                padding: 14px 16px;
                background: #fff;
                border: 1px solid rgba(27, 38, 49, 0.08);
            }
            .ib-kpi-label {
                font-size: 0.82rem;
                color: #6b7280;
                margin-bottom: 6px;
            }
            .ib-kpi-value {
                font-size: 1.35rem;
                font-weight: 800;
                color: #17202a;
            }
            .ib-list {
                margin: 0;
                padding-left: 1.1rem;
            }
            .ib-list li {
                margin-bottom: 0.35rem;
                line-height: 1.45;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

    def render_status_chip(status: str) -> None:
        chip_map = {
            "success": ("调试成功", "ib-chip-success"),
            "empty": ("无命中内容", "ib-chip-warning"),
            "empty_candidates": ("暂无候选", "ib-chip-warning"),
            "error": ("调试失败", "ib-chip-error"),
        }
        label, css_class = chip_map.get(status, ("状态未知", "ib-chip-neutral"))
        st.markdown(
            f'<div class="ib-chip-row"><span class="ib-chip {css_class}">{label}</span></div>',
            unsafe_allow_html=True,
        )

    def render_health_chip(status: str) -> str:
        chip_map = {
            "ok": ("正常", "ib-chip-success"),
            "stale": ("无更新", "ib-chip-warning"),
            "error": ("错误", "ib-chip-error"),
        }
        label, css_class = chip_map.get(status, ("未知", "ib-chip-neutral"))
        return f'<span class="ib-chip {css_class}">{label}</span>'

    def render_kpi_strip(*, candidate_count: int, selected_count: int, using_fallback: bool, prompt_changed: bool) -> None:
        fallback_label = "内置样例" if using_fallback else "真实 RSS"
        draft_state = "已修改" if prompt_changed else "与当前一致"
        st.markdown(
            f"""
            <div class="ib-kpi-grid">
              <div class="ib-kpi-card">
                <div class="ib-kpi-label">候选条数</div>
                <div class="ib-kpi-value">{candidate_count}</div>
              </div>
              <div class="ib-kpi-card">
                <div class="ib-kpi-label">命中条数</div>
                <div class="ib-kpi-value">{selected_count}</div>
              </div>
              <div class="ib-kpi-card">
                <div class="ib-kpi-label">候选来源</div>
                <div class="ib-kpi-value" style="font-size:1.05rem;">{fallback_label}</div>
              </div>
              <div class="ib-kpi-card">
                <div class="ib-kpi-label">草稿状态</div>
                <div class="ib-kpi-value" style="font-size:1.05rem;">{draft_state}</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    def render_result_panel(*, title: str, result: dict) -> None:
        status = result.get("status", "unknown")
        selected_items = result.get("selected_items", [])
        preview_md = result.get("preview_markdown", "")

        st.markdown(f"**{title}**")
        render_status_chip(status)
        if status == "success":
            st.success(f"候选 {result.get('candidate_count', 0)} 条，命中 {len(selected_items)} 条。")
        elif status == "empty":
            st.warning(f"候选 {result.get('candidate_count', 0)} 条，但没有命中内容。")
        elif status == "empty_candidates":
            st.warning("当前没有可调试的候选内容。")
        else:
            st.error(f"调试失败：{result.get('error', '未知错误')}")

        if selected_items:
            with st.expander(f"{title} 命中内容", expanded=False):
                for idx, item in enumerate(selected_items, start=1):
                    item_title = item.get("title", "").strip()
                    item_url = item.get("url", "").strip()
                    item_summary = item.get("summary", "").strip()
                    st.markdown(f"**{idx}. [{item_title}]({item_url})**")
                    st.caption(item_summary or "无摘要")

        if preview_md:
            st.markdown(preview_md)
        else:
            st.info("本次没有生成可预览输出。")

        with st.expander(f"{title} 批次详情", expanded=status != "success"):
            st.json(
                {
                    "status": status,
                    "selected_items": selected_items,
                    "batches": result.get("batches", []),
                },
                expanded=False,
            )

    def format_timestamp(value: str | None) -> str:
        if not value:
            return "—"
        try:
            return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return value

    def is_today(value: str | None) -> bool:
        if not value:
            return False
        try:
            return datetime.fromisoformat(value).date() == datetime.now().date()
        except ValueError:
            return False

    def render_operating_chip(label: str, css_class: str) -> None:
        st.markdown(
            f'<div class="ib-chip-row"><span class="ib-chip {css_class}">{label}</span></div>',
            unsafe_allow_html=True,
        )

    def summarize_cache_age(seconds: int | None) -> str:
        if seconds is None:
            return "未知"
        if seconds < 60:
            return f"{seconds}s"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} 分钟"
        hours = minutes // 60
        return f"{hours} 小时"

    def derive_task_state(validation_result: dict, latest_run: dict | None, latest_success: dict | None, task_state: dict | None) -> tuple[str, str, str]:
        if not validation_result.get("is_runnable"):
            return ("未配置完成", "ib-chip-error", "当前任务还有关键配置缺失，先补齐后再运行。")
        if task_state and task_state.get("needs_revalidation"):
            return ("待重新验证", "ib-chip-warning", "最近配置发生变更，建议重新跑 Dry Run 并刷新健康度。")
        if latest_run and latest_run.get("ok") is False:
            return ("运行失败", "ib-chip-error", "最近一次任务执行失败，建议先看日志和诊断卡片。")
        if latest_success and is_today(latest_success.get("started_at")):
            return ("今日已发送", "ib-chip-success", "今天已经成功发出内容。")
        if latest_run and is_today(latest_run.get("started_at")):
            return ("今日已运行", "ib-chip-warning", "今天跑过任务，但还没有确认成功发送。")
        if validation_result.get("status") == "needs_attention":
            return ("待关注", "ib-chip-warning", "任务可运行，但仍有风险项需要关注。")
        return ("可运行", "ib-chip-success", "当前配置完整，可以进入稳定运行。")

    def render_validation_result(validation_result: dict, *, task_state: dict | None = None) -> None:
        status_map = {
            "ready": ("可运行", "ib-chip-success"),
            "needs_attention": ("待关注", "ib-chip-warning"),
            "not_ready": ("不可运行", "ib-chip-error"),
        }
        label, css_class = status_map.get(validation_result.get("status"), ("状态未知", "ib-chip-neutral"))
        st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
        st.markdown('<div class="ib-section-title">任务配置校验</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="ib-section-copy">保存后会基于当前任务检查板块、RSS、频道和调度是否完整。</div>',
            unsafe_allow_html=True,
        )
        render_operating_chip(label, css_class)
        summary = validation_result.get("summary", {})
        st.caption(
            f"板块 {summary.get('category_count', 0)} 个 | RSS {summary.get('feed_count', 0)} 个 | "
            f"频道 {summary.get('channel_count', 0)} 个 | 调度 {'已配置' if summary.get('has_schedule') else '未配置'}"
        )
        if task_state and task_state.get("needs_revalidation"):
            st.warning("当前任务最近配置已变更，建议重新 Dry Run 并刷新健康度。")
        issues = validation_result.get("issues", [])
        if not issues:
            st.success("当前没有发现配置缺口。")
        else:
            for item in issues:
                line = f"{item.get('message', '未知问题')}（{item.get('field_path', 'unknown')}）"
                if item.get("level") == "error":
                    st.error(line)
                else:
                    st.warning(line)
        st.markdown("</div>", unsafe_allow_html=True)

    def render_verification_summary(
        *,
        latest_run: dict | None,
        latest_success: dict | None,
        health_snapshot: dict | None,
        task_state: dict | None,
        prompt_history: list[dict],
    ) -> None:
        last_debug_at = prompt_history[0].get("created_at") if prompt_history else None
        st.markdown(
            f"""
            <div class="ib-kpi-grid">
              <div class="ib-kpi-card">
                <div class="ib-kpi-label">最近运行</div>
                <div class="ib-kpi-value" style="font-size:1.05rem;">{format_timestamp((latest_run or {}).get('started_at'))}</div>
              </div>
              <div class="ib-kpi-card">
                <div class="ib-kpi-label">最后成功发送</div>
                <div class="ib-kpi-value" style="font-size:1.05rem;">{format_timestamp((latest_success or {}).get('started_at'))}</div>
              </div>
              <div class="ib-kpi-card">
                <div class="ib-kpi-label">最近健康检查</div>
                <div class="ib-kpi-value" style="font-size:1.05rem;">{format_timestamp((health_snapshot or {}).get('checked_at'))}</div>
              </div>
              <div class="ib-kpi-card">
                <div class="ib-kpi-label">最近调试</div>
                <div class="ib-kpi-value" style="font-size:1.05rem;">{format_timestamp(last_debug_at)}</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if task_state and task_state.get("needs_revalidation"):
            st.warning("当前任务最近有配置变更，建议按顺序执行：刷新健康度 -> Dry Run/板块调试 -> 正式运行。")

    def load_recent_log_excerpt(limit: int = 120) -> str:
        if not os.path.exists(bot_log_path):
            return ""
        try:
            with open(bot_log_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except OSError:
            return ""
        filtered = filter_log_lines_for_task(lines, selected_task_id)
        return "".join((filtered or lines)[-limit:])

    def render_diagnosis_card(card: dict, *, prompt_categories: list[str], key_prefix: str) -> None:
        st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
        st.markdown(f'<div class="ib-section-title">{card["title"]}</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="ib-section-copy">{card["summary"]}<br/>下一步：{card["next_step"]}</div>',
            unsafe_allow_html=True,
        )
        kind = card.get("kind")
        detail_categories = [item.get("category") for item in card.get("details", []) if item.get("category")]
        default_category = detail_categories[0] if detail_categories else None
        if default_category:
            action_col1, action_col2 = st.columns(2)
            with action_col1:
                if st.button(
                    f"🎯 聚焦板块：{default_category}",
                    key=f"{key_prefix}_diag_focus_{default_category}",
                    use_container_width=True,
                ):
                    set_verification_focus(selected_task_id, default_category)
                    st.rerun()
            with action_col2:
                if kind == "prompt_block" and st.button(
                    f"🧠 准备调试：{default_category}",
                    key=f"{key_prefix}_diag_prompt_{default_category}",
                    use_container_width=True,
                ):
                    set_prompt_debug_category(selected_task_id, default_category)
                    candidate_count, using_fallback = seed_prompt_debug_candidates(selected_task_id, default_category)
                    status_text = "内置样例" if using_fallback else "真实 RSS"
                    st.success(f"已为 [{default_category}] 准备调试上下文，并抓取 {candidate_count} 条候选（{status_text}）。")
        if kind == "prompt_block":
            if default_category is None:
                st.caption("建议在当前页下方的“板块调试”区域直接试跑草稿 Prompt，优先排查被拦截的板块。")
        elif kind == "source_error":
            st.caption("建议先在当前页的 RSS 健康度列表里查看这些异常源。")
        elif kind == "no_candidates":
            st.caption("建议先聚焦该板块看 RSS 健康度；如果源本身长期无更新，再考虑补源或改抓取范围。")
        elif kind == "runtime_error":
            st.caption("建议切到“📝 运行日志”查看完整错误上下文。")

        details = card.get("details", [])
        if details:
            with st.expander("查看诊断细节", expanded=False):
                st.json(details, expanded=False)
        st.markdown("</div>", unsafe_allow_html=True)

    def render_history_status(label: str, status: str | None, count: int | None) -> str:
        if status is None:
            return f"{label}: —"
        label_map = {
            "success": "成功",
            "empty": "空结果",
            "empty_candidates": "无候选",
            "error": "错误",
        }
        count_text = f" / 命中 {count}" if count is not None else ""
        return f"{label}: {label_map.get(status, status)}{count_text}"

    def filter_prompt_history_for_task(items: list[dict], task_id: str | None) -> list[dict]:
        if not task_id:
            return items
        scoped = [item for item in items if item.get("task_id") == task_id]
        return scoped if scoped else items

    def filter_log_lines_for_task(lines: list[str], task_id: str | None) -> list[str]:
        if not task_id:
            return lines
        needle = task_id.lower()
        matched = [line for line in lines if needle in line.lower()]
        return matched if matched else lines

    def get_editorial_defaults() -> dict:
        editorial_config = (config.get("ai", {}) or {}).get("editorial_pipeline", {})
        return {
            "global_shortlist_multiplier": editorial_config.get("global_shortlist_multiplier", 3),
            "assignment_batch_size": editorial_config.get("assignment_batch_size", 20),
            "allow_multi_assign": editorial_config.get("allow_multi_assign", False),
            "inject_publication_scope_into_global": editorial_config.get(
                "inject_publication_scope_into_global", True
            ),
        }

    def get_tasks_data() -> dict:
        tasks_data = load_tasks(bot_dir)
        return tasks_data if "tasks" in tasks_data else {"tasks": {}}

    def get_selected_task_id(tasks_data: dict) -> str | None:
        task_ids = list(tasks_data.get("tasks", {}).keys())
        if not task_ids:
            st.session_state.pop("selected_task_id", None)
            st.session_state.pop("current_task_selector", None)
            return None
        selector_value = st.session_state.get("current_task_selector")
        if selector_value in task_ids:
            current = selector_value
        else:
            current = st.session_state.get("selected_task_id")
            if current not in task_ids:
                current = task_ids[0]
        st.session_state["selected_task_id"] = current
        st.session_state["current_task_selector"] = current
        return current

    def get_selected_task(tasks_data: dict) -> tuple[str | None, dict]:
        task_id = get_selected_task_id(tasks_data)
        if not task_id:
            return None, {}
        return task_id, tasks_data["tasks"].get(task_id, {})

    def mark_task_changed(task_id: str) -> dict:
        runtime_view = build_task_runtime_config(task_id)
        revision = build_task_revision(runtime_view)
        clear_task_health(task_id, bot_dir)
        state = touch_revalidation_state(
            task_id=task_id,
            config_revision=revision,
            needs_revalidation=True,
            bot_dir=bot_dir,
        )
        st.session_state[f"task_state::{task_id}"] = state
        return state

    def mark_tasks_changed(task_ids: list[str]) -> None:
        for task_id in task_ids:
            mark_task_changed(task_id)

    def save_task_definition(task_id: str, task_def: dict) -> None:
        tasks_data = get_tasks_data()
        tasks_data.setdefault("tasks", {})
        tasks_data["tasks"][task_id] = task_def
        save_tasks(tasks_data, bot_dir)
        scheduler.reload()
        mark_task_changed(task_id)

    def build_task_runtime_config(task_id: str | None) -> dict:
        if not task_id:
            return runtime_config
        try:
            return load_tasks_config(task_id, bot_dir)
        except Exception:
            return runtime_config

    def add_rss_feed_to_task(task_id: str, category: str, feed_url: str, feed_name: str = "") -> bool:
        """Add a single RSS feed into a task category."""
        try:
            tasks_data = get_tasks_data()
            task_def = deepcopy(tasks_data["tasks"].get(task_id, {}))
            task_feeds = task_def.setdefault("feeds", {})
            if category not in task_feeds:
                task_feeds[category] = {"rss": [], "keywords": [], "prompt": ""}

            existing_urls = [
                item.split(" # ")[0].strip() if isinstance(item, str) else item.get("feed_url", "")
                for item in task_feeds[category].get("rss", [])
            ]
            if feed_url in existing_urls:
                return False

            entry = f"{feed_url} # {feed_name}" if feed_name else feed_url
            task_feeds[category].setdefault("rss", []).append(entry)
            tasks_data["tasks"][task_id] = task_def
            save_tasks(tasks_data, bot_dir)
            scheduler.reload()
            mark_task_changed(task_id)
            return True
        except Exception as e:
            st.error(f"淇濆瓨澶辫触: {e}")
            return False

    config = load_config()
    runtime_config = load_runtime_view()

    # Load tasks and channels; create scheduler (auto-migrates v1 config if needed)
    channels_data = load_channels(bot_dir)
    init_channels(channels_data)
    scheduler = create_scheduler(bot_dir)
    tasks_data = get_tasks_data()
    selected_task_id, selected_task = get_selected_task(tasks_data)
    selected_task_runtime_config = build_task_runtime_config(selected_task_id)
    selected_task_feeds = deepcopy(selected_task.get("feeds", {})) if selected_task else {}
    selected_task_categories = list(selected_task_feeds.keys())
    selected_task_state = load_task_state(selected_task_id, bot_dir) if selected_task_id else {}
    if selected_task_id:
        current_revision = build_task_revision(selected_task_runtime_config)
        if selected_task_state.get("config_revision") != current_revision:
            selected_task_state = touch_revalidation_state(
                task_id=selected_task_id,
                config_revision=current_revision,
                needs_revalidation=True,
                bot_dir=bot_dir,
                last_validated_revision=selected_task_state.get("last_validated_revision"),
            )
    else:
        current_revision = ""
    selected_task_validation = (
        validate_task_definition(selected_task_id, selected_task, channels_data)
        if selected_task_id and selected_task
        else {"status": "not_ready", "is_runnable": False, "issues": [], "summary": {}}
    )

    st.set_page_config(page_title="营销情报站 | 控制台", layout="wide")
    render_prompt_debug_styles()
    st.title("🚀 营销情报站 | 智控中心")
    st.caption(f"当前编辑配置文件: {active_edit_path}")

    if "settings" not in config:
        config["settings"] = {}
    if "ai" not in config:
        config["ai"] = {}

    with st.sidebar:
        st.header("⚡ 快捷操作")
        task_ids = list(tasks_data.get("tasks", {}).keys())
        if task_ids:
            active_task_id = st.selectbox(
                "当前任务",
                options=task_ids,
                index=task_ids.index(selected_task_id) if selected_task_id in task_ids else 0,
                key="current_task_selector",
            )
            selected_task_id = active_task_id
            st.session_state["selected_task_id"] = active_task_id
            selected_task = tasks_data["tasks"].get(selected_task_id, {})
            selected_task_runtime_config = build_task_runtime_config(selected_task_id)
            selected_task_feeds = deepcopy(selected_task.get("feeds", {}))
            selected_task_categories = list(selected_task_feeds.keys())
            selected_task_state = load_task_state(selected_task_id, bot_dir)
            current_revision = build_task_revision(selected_task_runtime_config)
            if selected_task_state.get("config_revision") != current_revision:
                selected_task_state = touch_revalidation_state(
                    task_id=selected_task_id,
                    config_revision=current_revision,
                    needs_revalidation=True,
                    bot_dir=bot_dir,
                    last_validated_revision=selected_task_state.get("last_validated_revision"),
                )
            selected_task_validation = validate_task_definition(selected_task_id, selected_task, channels_data)
            st.caption(
                f"Pipeline: `{selected_task.get('pipeline', 'editorial')}` | "
                f"Channels: {len(selected_task.get('channels', []))} | "
                f"Categories: {len(selected_task_categories)}"
            )
        else:
            st.info("暂无任务，请先在任务管理页面创建。")

        st.markdown("**➕ 创建新任务**")
        quick_new_task_id = st.text_input(
            "任务 ID",
            placeholder="e.g. weekly_report",
            key="quick_create_task_id",
        )
        quick_new_task_name = st.text_input(
            "任务名称",
            placeholder="每周深度报告",
            key="quick_create_task_name",
        )
        quick_col1, quick_col2, quick_col3 = st.columns([1.2, 1, 1])
        with quick_col1:
            quick_new_task_pipeline = st.selectbox(
                "Pipeline",
                options=["editorial", "classic"],
                index=0,
                key="quick_create_task_pipeline",
            )
        with quick_col2:
            quick_new_task_hour = st.number_input("小时", 0, 23, 8, key="quick_create_task_hour")
        with quick_col3:
            quick_new_task_min = st.number_input("分钟", 0, 59, 0, key="quick_create_task_min")

        if st.button("创建任务", key="quick_create_task_btn", use_container_width=True):
            tasks_data = get_tasks_data()
            tasks = tasks_data.get("tasks", {})
            if quick_new_task_id and quick_new_task_id not in tasks:
                tasks[quick_new_task_id] = {
                    "name": quick_new_task_name or quick_new_task_id,
                    "enabled": False,
                    "pipeline": quick_new_task_pipeline,
                    "feeds": deepcopy(selected_task_feeds or config.get("feeds", {})),
                    "pipeline_config": deepcopy(get_editorial_defaults()),
                    "search": deepcopy((selected_task or {}).get("search", config.get("search", {}))),
                    "channels": deepcopy((selected_task or {}).get("channels", [])),
                    "schedule": {"hour": int(quick_new_task_hour), "minute": int(quick_new_task_min)},
                }
                save_tasks(tasks_data, bot_dir)
                scheduler.reload()
                mark_task_changed(quick_new_task_id)
                st.session_state["selected_task_id"] = quick_new_task_id
                st.success(f"任务「{quick_new_task_id}」已创建。")
                st.rerun()
            elif quick_new_task_id in tasks:
                st.error("任务 ID 已存在。")

        if st.button("▶️ 立即手动运行", type="primary", use_container_width=True):
            with st.spinner("AI 正在全网检索并撰写简报..."):
                subprocess.run([sys.executable, "-m", "insightbot.cli"])
                st.success("运行指令已发送，请查看企业微信或日志。")

        st.divider()
        st.header("⏳ 调度器状态")

        tasks_def = load_tasks(bot_dir)  # reload to show current
        enabled_count = sum(1 for t in tasks_def.get("tasks", {}).values() if t.get("enabled"))
        total_count = len(tasks_def.get("tasks", {}))
        st.metric("活跃任务", f"{enabled_count}/{total_count}")

        if st.button("🚀 运行所有已启用任务", use_container_width=True):
            with st.spinner("正在运行所有已启用任务..."):
                results = scheduler.run_all_enabled()
            for r in results:
                status = "✅" if r.get("ok") else "❌"
                st.write(f"{status} {r.get('task_id')}")
            st.success("任务运行完成！")

        st.divider()
        st.header("📡 Channels")
        channels_data = load_channels(bot_dir)
        channel_count = len(channels_data.get("channels", {}))
        st.metric("已配置频道", str(channel_count))

        st.caption("在「📡 Channels」标签页管理频道配置和联通性测试。")

    overview_health_snapshot = load_task_health(selected_task_id, bot_dir) if selected_task_id else None
    overview_run_summary = parse_recent_run_summary(bot_log_path)
    overview_run_metrics = summarize_recent_run(overview_run_summary)
    overview_diagnosis_cards = build_no_push_diagnosis(
        health_snapshot=overview_health_snapshot,
        run_summary=overview_run_summary,
        configured_categories=selected_task_categories,
    )
    overview_prompt_history = filter_prompt_history_for_task(load_prompt_debug_history(bot_dir), selected_task_id)
    latest_run_record = get_latest_run(selected_task_id, bot_dir) if selected_task_id else None
    latest_success_record = get_latest_successful_send(selected_task_id, bot_dir) if selected_task_id else None
    task_state_label, task_state_class, task_state_copy = derive_task_state(
        selected_task_validation,
        latest_run_record,
        latest_success_record,
        selected_task_state,
    )

    tab0, tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "🏠 概览", "📋 任务管理", "📡 Channels",
        "🧪 验证与调试", "📝 运行日志",
        "⚙️ 推送版式定制", "🔬 任务调试",
    ])

    with tab0:
        st.subheader("运营概览")
        active_task_name = selected_task.get("name", selected_task_id) if selected_task_id else "未选择任务"
        st.caption(f"当前聚焦任务：{active_task_name}。优先看最近一次运行、异常摘要和最近调试动作。")
        if selected_task_id:
            st.markdown(
                f'<div class="ib-chip-row"><span class="ib-chip ib-chip-neutral">任务 ID: {selected_task_id}</span>'
                f'<span class="ib-chip ib-chip-neutral">任务名: {active_task_name}</span></div>',
                unsafe_allow_html=True,
            )

        health_counts = (overview_health_snapshot or {}).get("counts", {})
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
                  最近运行结果：{overview_run_metrics.get('result_label', '未知')}
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
            if overview_prompt_history:
                for item in overview_prompt_history[:3]:
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
        if overview_diagnosis_cards:
            for card in overview_diagnosis_cards[:3]:
                render_diagnosis_card(
                    card,
                    prompt_categories=selected_task_categories,
                    key_prefix="overview",
                )
        else:
            st.success("当前没有明显异常摘要，系统状态看起来比较稳定。")
        st.markdown("</div>", unsafe_allow_html=True)

    # ── Tab 1: 任务管理 ────────────────────────────────────────────────────────
    with tab1:
        st.subheader("📋 任务管理")
        st.caption("把任务当成真正的产品单元来配置：内容源、搜索补充、筛选策略、频道与调度都在这里。")

        tasks = tasks_data.get("tasks", {})
        if not tasks or not selected_task_id:
            st.info("暂没有任务，请先在下方创建。")
        else:
            task_def = deepcopy(tasks.get(selected_task_id, {}))
            st.markdown(f"**当前任务：{task_def.get('name', selected_task_id)}**")

            basic_col1, basic_col2 = st.columns([1, 2])
            with basic_col1:
                new_enabled = st.checkbox("启用任务", value=task_def.get("enabled", False), key=f"task_enabled_{selected_task_id}")
            with basic_col2:
                new_name = st.text_input("任务名称", value=task_def.get("name", ""), key=f"task_name_{selected_task_id}")

            meta_col1, meta_col2, meta_col3, meta_col4 = st.columns([1.2, 1, 1, 1.3])
            with meta_col1:
                pipeline_options = ["editorial", "classic"]
                pipeline_value = task_def.get("pipeline", "editorial")
                if pipeline_value not in pipeline_options:
                    pipeline_value = "editorial"
                new_pipeline = st.selectbox(
                    "Pipeline",
                    options=pipeline_options,
                    index=pipeline_options.index(pipeline_value),
                    key=f"task_pipeline_{selected_task_id}",
                )
            with meta_col2:
                new_hour = st.number_input(
                    "小时",
                    min_value=0,
                    max_value=23,
                    value=int(task_def.get("schedule", {}).get("hour", 8)),
                    key=f"task_hour_{selected_task_id}",
                )
            with meta_col3:
                new_min = st.number_input(
                    "分钟",
                    min_value=0,
                    max_value=59,
                    value=int(task_def.get("schedule", {}).get("minute", 0)),
                    key=f"task_min_{selected_task_id}",
                )
            with meta_col4:
                day_options = [
                    ("每天", None),
                    ("周一", 0),
                    ("周二", 1),
                    ("周三", 2),
                    ("周四", 3),
                    ("周五", 4),
                    ("周六", 5),
                    ("周日", 6),
                ]
                current_day = task_def.get("schedule", {}).get("day_of_week")
                day_index = next((i for i, item in enumerate(day_options) if item[1] == current_day), 0)
                selected_day_label = st.selectbox(
                    "执行日",
                    options=[item[0] for item in day_options],
                    index=day_index,
                    key=f"task_day_{selected_task_id}",
                )

            channels_data = load_channels(bot_dir)
            all_channel_ids = list(channels_data.get("channels", {}).keys())
            selected_channels = st.multiselect(
                "目标频道",
                options=all_channel_ids,
                default=task_def.get("channels", []),
                key=f"task_channels_{selected_task_id}",
            )

            st.markdown("**内容板块与 RSS**")
            feeds_editor = deepcopy(task_def.get("feeds", {}))
            category_to_delete = None
            for category, feed_data in feeds_editor.items():
                with st.expander(f"📂 {category}", expanded=False):
                    rss_val = "\n".join(feed_data.get("rss", []))
                    feeds_editor[category]["rss"] = [
                        x.strip()
                        for x in st.text_area(
                            "RSS 源（每行一个）",
                            value=rss_val,
                            height=120,
                            key=f"task_rss_{selected_task_id}_{category}",
                        ).split("\n")
                        if x.strip()
                    ]
                    kw_val = "\n".join(feed_data.get("keywords", []))
                    feeds_editor[category]["keywords"] = [
                        x.strip()
                        for x in st.text_area(
                            "关键词（每行一个）",
                            value=kw_val,
                            height=90,
                            key=f"task_kw_{selected_task_id}_{category}",
                        ).split("\n")
                        if x.strip()
                    ]
                    feeds_editor[category]["prompt"] = st.text_area(
                        "板块筛选 Prompt",
                        value=feed_data.get("prompt", ""),
                        height=110,
                        key=f"task_prompt_{selected_task_id}_{category}",
                    ).strip()
                    if st.button("删除板块", key=f"del_task_cat_{selected_task_id}_{category}"):
                        category_to_delete = category

            if category_to_delete:
                feeds_editor.pop(category_to_delete, None)
                task_def["feeds"] = feeds_editor
                save_task_definition(selected_task_id, task_def)
                st.success(f"已删除板块：{category_to_delete}")
                st.rerun()

            add_cat_col1, add_cat_col2 = st.columns([3, 1])
            with add_cat_col1:
                new_category_name = st.text_input(
                    "新增板块名称",
                    placeholder="例如：品牌营销动态",
                    key=f"new_task_category_{selected_task_id}",
                )
            with add_cat_col2:
                if st.button("添加板块", key=f"add_task_category_{selected_task_id}", use_container_width=True):
                    if new_category_name.strip():
                        feeds_editor.setdefault(
                            new_category_name.strip(),
                            {"rss": [], "keywords": [], "prompt": ""},
                        )
                        task_def["feeds"] = feeds_editor
                        save_task_definition(selected_task_id, task_def)
                        st.success(f"已添加板块：{new_category_name.strip()}")
                        st.rerun()

            st.divider()
            st.markdown("**搜索补充**")
            search_config = deepcopy(task_def.get("search", {}))
            search_enabled = st.toggle(
                "启用搜索补充",
                value=search_config.get("enabled", False),
                key=f"task_search_enabled_{selected_task_id}",
            )
            search_provider_options = ["baidu", "duckduckgo"]
            search_provider = search_config.get("provider", "baidu")
            if search_provider not in search_provider_options:
                search_provider = "baidu"
            search_provider = st.selectbox(
                "搜索引擎",
                options=search_provider_options,
                index=search_provider_options.index(search_provider),
                key=f"task_search_provider_{selected_task_id}",
            )

            query_state_key = f"task_search_queries::{selected_task_id}"
            if query_state_key not in st.session_state:
                st.session_state[query_state_key] = deepcopy(search_config.get("queries", []))

            search_queries = st.session_state[query_state_key]
            query_to_delete = None
            for idx, query in enumerate(search_queries):
                q_col1, q_col2, q_col3, q_col4 = st.columns([4, 2, 1, 1])
                with q_col1:
                    query["keywords"] = st.text_input(
                        "关键词",
                        value=query.get("keywords", ""),
                        key=f"task_search_keywords_{selected_task_id}_{idx}",
                        label_visibility="collapsed",
                        placeholder="品牌 AI 营销 新动作",
                    )
                with q_col2:
                    query["category_hint"] = st.selectbox(
                        "板块 hint",
                        options=[""] + list(feeds_editor.keys()),
                        index=([""] + list(feeds_editor.keys())).index(query.get("category_hint", ""))
                        if query.get("category_hint", "") in [""] + list(feeds_editor.keys())
                        else 0,
                        key=f"task_search_hint_{selected_task_id}_{idx}",
                        label_visibility="collapsed",
                    )
                with q_col3:
                    query["max_results"] = st.number_input(
                        "最大结果",
                        min_value=1,
                        max_value=30,
                        value=int(query.get("max_results", 10)),
                        key=f"task_search_max_{selected_task_id}_{idx}",
                        label_visibility="collapsed",
                    )
                with q_col4:
                    if st.button("🗑️", key=f"task_search_del_{selected_task_id}_{idx}"):
                        query_to_delete = idx

            if query_to_delete is not None:
                del search_queries[query_to_delete]
                st.session_state[query_state_key] = search_queries
                st.rerun()

            q_action1, q_action2 = st.columns([1, 1])
            with q_action1:
                if st.button("添加 Query", key=f"task_search_add_{selected_task_id}", use_container_width=True):
                    search_queries.append({"keywords": "", "category_hint": "", "max_results": 10})
                    st.session_state[query_state_key] = search_queries
                    st.rerun()
            with q_action2:
                if st.button("从板块关键词派生", key=f"task_search_derive_{selected_task_id}", use_container_width=True):
                    derived_queries = []
                    for category, feed_data in feeds_editor.items():
                        keywords = [kw.strip() for kw in feed_data.get("keywords", []) if kw.strip()]
                        if keywords:
                            derived_queries.append(
                                {"keywords": " ".join(keywords), "category_hint": category, "max_results": 10}
                            )
                    st.session_state[query_state_key] = derived_queries
                    st.rerun()

            st.divider()
            st.markdown("**Editorial Pipeline 策略**")
            pipeline_config = deepcopy(task_def.get("pipeline_config", {}))
            editorial_defaults = get_editorial_defaults()
            pipe_col1, pipe_col2, pipe_col3, pipe_col4 = st.columns(4)
            with pipe_col1:
                pipeline_config["global_shortlist_multiplier"] = st.slider(
                    "初筛倍率",
                    min_value=1,
                    max_value=8,
                    value=int(pipeline_config.get("global_shortlist_multiplier", editorial_defaults["global_shortlist_multiplier"])),
                    key=f"task_pipe_multiplier_{selected_task_id}",
                )
            with pipe_col2:
                pipeline_config["assignment_batch_size"] = st.slider(
                    "分配批大小",
                    min_value=5,
                    max_value=40,
                    value=int(pipeline_config.get("assignment_batch_size", editorial_defaults["assignment_batch_size"])),
                    key=f"task_pipe_batch_{selected_task_id}",
                )
            with pipe_col3:
                pipeline_config["allow_multi_assign"] = st.toggle(
                    "允许多板块分配",
                    value=bool(pipeline_config.get("allow_multi_assign", editorial_defaults["allow_multi_assign"])),
                    key=f"task_pipe_multi_{selected_task_id}",
                )
            with pipe_col4:
                pipeline_config["inject_publication_scope_into_global"] = st.toggle(
                    "注入发布范围",
                    value=bool(
                        pipeline_config.get(
                            "inject_publication_scope_into_global",
                            editorial_defaults["inject_publication_scope_into_global"],
                        )
                    ),
                    key=f"task_pipe_scope_{selected_task_id}",
                )

            st.divider()
            with st.expander("高级 AI 设置", expanded=False):
                st.caption("Editorial 流程已经更像一个 skill，控制台这里只保留高频的全局策略入口。底层执行细节优先在“验证与调试”里就地调试。")

                ai_config = deepcopy(config.get("ai", {}) or {})
                selection_settings = get_selection_settings(selected_task_runtime_config)
                secrets_view = load_secrets_config()
                merged_ai_view = deepcopy((runtime_config.get("ai", {}) or {}))

                env_overrides = [
                    env_name for env_name in ("AI_API_KEY", "AI_API_URL", "AI_MODEL")
                    if os.getenv(env_name)
                ]
                if env_overrides:
                    st.warning(f"检测到环境变量覆盖：{', '.join(env_overrides)}。界面中的保存值可能不会在当前运行环境里立即生效。")

                ai_prompt = st.text_area(
                    "全局 System Prompt",
                    value=ai_config.get("system_prompt", merged_ai_view.get("system_prompt", "")),
                    height=180,
                    key=f"task_global_system_prompt_{selected_task_id}",
                ).strip()

                st.markdown("**输出筛选规则**")
                rule_col1, rule_col2, rule_col3 = st.columns(3)
                with rule_col1:
                    selection_max_items = st.number_input(
                        "最多保留条数",
                        min_value=1,
                        max_value=20,
                        value=int(selection_settings.get("max_selected_items", 5)),
                        key=f"task_selection_max_items_{selected_task_id}",
                    )
                with rule_col2:
                    selection_title_max = st.number_input(
                        "标题最大字数",
                        min_value=10,
                        max_value=120,
                        value=int(selection_settings.get("title_max_len", 30)),
                        key=f"task_selection_title_max_{selected_task_id}",
                    )
                with rule_col3:
                    selection_summary_max = st.number_input(
                        "摘要最大字数",
                        min_value=10,
                        max_value=120,
                        value=int(selection_settings.get("summary_max_len", 50)),
                        key=f"task_selection_summary_max_{selected_task_id}",
                    )

                rule_col4, rule_col5 = st.columns(2)
                with rule_col4:
                    selection_threshold = st.number_input(
                        "全量分析阈值（字符）",
                        min_value=1000,
                        max_value=200000,
                        step=1000,
                        value=int(selection_settings.get("full_context_threshold_chars", 40000)),
                        key=f"task_selection_threshold_{selected_task_id}",
                    )
                with rule_col5:
                    selection_batch_size = st.number_input(
                        "分批分析大小",
                        min_value=1,
                        max_value=50,
                        value=int(selection_settings.get("batch_size", 15)),
                        key=f"task_selection_batch_size_{selected_task_id}",
                    )

                st.markdown("**运行时 AI 连接**")
                runtime_col1, runtime_col2 = st.columns(2)
                with runtime_col1:
                    runtime_model = st.text_input(
                        "模型名",
                        value=merged_ai_view.get("model", ""),
                        key=f"task_runtime_model_{selected_task_id}",
                    ).strip()
                    runtime_api_url = st.text_input(
                        "API URL",
                        value=merged_ai_view.get("api_url", ""),
                        key=f"task_runtime_api_url_{selected_task_id}",
                    ).strip()
                with runtime_col2:
                    runtime_api_key = st.text_input(
                        "API Key",
                        value=merged_ai_view.get("api_key", ""),
                        type="password",
                        key=f"task_runtime_api_key_{selected_task_id}",
                    ).strip()
                    st.caption("运行时凭证会优先写入 config.secrets.json；如果你改用本地 runtime，后续也可以完全迁移到环境变量。")

            save_col1, save_col2 = st.columns([1, 1])
            with save_col1:
                if st.button("💾 保存当前任务配置", key=f"save_task_all_{selected_task_id}", use_container_width=True):
                    selected_day_value = next(
                        item[1] for item in day_options if item[0] == selected_day_label
                    )
                    task_def["name"] = new_name
                    task_def["enabled"] = new_enabled
                    task_def["pipeline"] = new_pipeline
                    task_def["channels"] = selected_channels
                    task_def["feeds"] = feeds_editor
                    task_def["pipeline_config"] = pipeline_config
                    task_def["search"] = {
                        "enabled": search_enabled,
                        "provider": search_provider,
                        "queries": [q for q in search_queries if q.get("keywords", "").strip()],
                    }
                    task_def["schedule"] = {"hour": int(new_hour), "minute": int(new_min)}
                    if selected_day_value is not None:
                        task_def["schedule"]["day_of_week"] = selected_day_value
                    save_task_definition(selected_task_id, task_def)

                    config.setdefault("ai", {})
                    config["ai"]["system_prompt"] = ai_prompt
                    config["ai"]["selection"] = {
                        "max_selected_items": int(selection_max_items),
                        "title_max_len": int(selection_title_max),
                        "summary_max_len": int(selection_summary_max),
                        "full_context_threshold_chars": int(selection_threshold),
                        "batch_size": int(selection_batch_size),
                    }
                    save_config(config)

                    secrets_payload = load_secrets_config()
                    secrets_payload.setdefault("ai", {})
                    secrets_payload["ai"]["model"] = runtime_model
                    secrets_payload["ai"]["api_url"] = runtime_api_url
                    secrets_payload["ai"]["api_key"] = runtime_api_key
                    save_secrets_config(secrets_payload)

                    mark_task_changed(selected_task_id)
                    selected_task_state = load_task_state(selected_task_id, bot_dir)
                    selected_task_validation = validate_task_definition(
                        selected_task_id,
                        task_def,
                        load_channels(bot_dir),
                    )
                    st.success(f"任务「{task_def['name']}」已保存。")
            with save_col2:
                if st.button("🗑️ 删除当前任务", key=f"del_task_{selected_task_id}", use_container_width=True):
                    tasks_data = get_tasks_data()
                    tasks_data.get("tasks", {}).pop(selected_task_id, None)
                    save_tasks(tasks_data, bot_dir)
                    scheduler.reload()
                    st.session_state.pop(f"task_search_queries::{selected_task_id}", None)
                    next_task_id = next(iter(tasks_data.get("tasks", {})), None)
                    st.session_state["selected_task_id"] = next_task_id
                    st.success("任务已删除。")
                    st.rerun()

            render_validation_result(selected_task_validation, task_state=selected_task_state)

    # ── Tab 2: Channels ────────────────────────────────────────────────────────
    with tab2:
        st.subheader("📡 Channels")
        st.caption("配置消息推送渠道（企业微信为主），测试联通性。")

        channels_data = load_channels(bot_dir)
        if "channels" not in channels_data:
            channels_data = {"channels": {}}

        channel_ids = list(channels_data["channels"].keys())
        for ch_id in channel_ids:
            ch = channels_data["channels"][ch_id]
            with st.expander(f"**{ch.get('name', ch_id)}** (`{ch_id}`)"):
                col1, col2 = st.columns([1, 1])
                with col1:
                    new_ch_name = st.text_input("名称", value=ch.get("name", ""), key=f"ch_name_{ch_id}")
                with col2:
                    new_ch_type = st.selectbox(
                        "类型",
                        options=["wecom"],
                        index=0,
                        key=f"ch_type_{ch_id}",
                    )
                new_cid = st.text_input("Corp ID (cid)", value=ch.get("cid", ""), key=f"ch_cid_{ch_id}")
                new_secret = st.text_input("Secret", value=ch.get("secret", ""), type="password", key=f"ch_secret_{ch_id}")
                new_agent_id = st.text_input("Agent ID", value=ch.get("agent_id", ""), key=f"ch_agent_{ch_id}")

                col_btn1, col_btn2, col_btn3 = st.columns(3)
                with col_btn1:
                    if st.button("💾 保存", key=f"ch_save_{ch_id}"):
                        channels_data["channels"][ch_id] = {
                            "type": new_ch_type,
                            "name": new_ch_name,
                            "cid": new_cid,
                            "secret": new_secret,
                            "agent_id": new_agent_id,
                        }
                        save_channels(channels_data, bot_dir)
                        init_channels(channels_data)
                        mark_tasks_changed(list(get_tasks_data().get("tasks", {}).keys()))
                        st.success("已保存！")
                        st.rerun()
                with col_btn2:
                    if st.button("🧪 测试联通性", key=f"ch_test_{ch_id}"):
                        try:
                            ok = test_channel(ch_id)
                            if ok:
                                st.success("✅ 频道连通性测试成功！")
                            else:
                                st.error("❌ 频道连通性测试失败，请检查配置。")
                        except Exception as e:
                            st.error(f"错误: {e}")
                with col_btn3:
                    if st.button("🗑️ 删除", key=f"ch_del_{ch_id}"):
                        channels_data["channels"].pop(ch_id, None)
                        save_channels(channels_data, bot_dir)
                        init_channels(channels_data)
                        mark_tasks_changed(list(get_tasks_data().get("tasks", {}).keys()))
                        st.success("已删除！")
                        st.rerun()

        st.divider()
        st.markdown("**➕ 添加新频道**")
        col_n1, col_n2, col_n3 = st.columns([2, 1, 1])
        with col_n1:
            new_ch_id = st.text_input("频道 ID（唯一标识）", placeholder="wecom_test")
        with col_n2:
            new_ch_name_input = st.text_input("名称", placeholder="测试频道")
        with col_n3:
            new_ch_type_input = st.selectbox("类型", options=["wecom"], index=0)

        if st.button("添加频道", key="add_channel_btn"):
            if new_ch_id and new_ch_id not in channels_data["channels"]:
                channels_data["channels"][new_ch_id] = {
                    "type": new_ch_type_input,
                    "name": new_ch_name_input or new_ch_id,
                    "cid": "",
                    "secret": "",
                    "agent_id": "",
                }
                save_channels(channels_data, bot_dir)
                init_channels(channels_data)
                mark_tasks_changed(list(get_tasks_data().get("tasks", {}).keys()))
                st.success(f"频道「{new_ch_id}」已添加！")
                st.rerun()
            elif new_ch_id in channels_data["channels"]:
                st.error("频道 ID 已存在。")

    with tab3:
        st.subheader("验证与调试")
        st.caption("把最近运行、成功发送、健康检查、板块调试、No Push Diagnosis 和相关日志放在一页里，减少来回切页排查。")

        health_snapshot = load_task_health(selected_task_id, bot_dir) if selected_task_id else None
        run_summary = parse_recent_run_summary(bot_log_path)
        task_prompt_history = filter_prompt_history_for_task(load_prompt_debug_history(bot_dir), selected_task_id)
        focused_category = get_verification_focus(selected_task_id)

        st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
        st.markdown('<div class="ib-section-title">验证状态总览</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="ib-section-copy">先确认最近有没有运行、有没有成功发送、当前健康快照是不是最新，再决定是否继续调试。</div>',
            unsafe_allow_html=True,
        )
        render_verification_summary(
            latest_run=latest_run_record,
            latest_success=latest_success_record,
            health_snapshot=health_snapshot,
            task_state=selected_task_state,
            prompt_history=overview_prompt_history,
        )
        st.markdown("</div>", unsafe_allow_html=True)

        if focused_category:
            focus_col1, focus_col2 = st.columns([4, 1.2])
            with focus_col1:
                st.markdown(
                    f'<div class="ib-chip-row"><span class="ib-chip ib-chip-warning">当前聚焦板块：{focused_category}</span></div>',
                    unsafe_allow_html=True,
                )
            with focus_col2:
                if st.button("清除聚焦", use_container_width=True):
                    set_verification_focus(selected_task_id, None)
                    st.rerun()

            st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
            st.markdown('<div class="ib-section-title">聚焦板块下一步</div>', unsafe_allow_html=True)
            st.markdown(
                '<div class="ib-section-copy">先确认源健康，再准备候选并在当前页下方直接调试这个板块。</div>',
                unsafe_allow_html=True,
            )
            action_col1, action_col2 = st.columns(2)
            with action_col1:
                if st.button("🧠 设为当前调试板块", key=f"verification_prompt_debug::{focused_category}", use_container_width=True):
                    set_prompt_debug_category(selected_task_id, focused_category)
                    st.success(f"已把 [{focused_category}] 设为当前调试板块。")
            with action_col2:
                if st.button("📥 抓候选到调试区", key=f"verification_fetch_candidates::{focused_category}", use_container_width=True):
                    candidate_count, using_fallback = seed_prompt_debug_candidates(selected_task_id, focused_category)
                    set_prompt_debug_category(selected_task_id, focused_category)
                    status_text = "内置样例" if using_fallback else "真实 RSS"
                    st.success(f"已为 [{focused_category}] 准备 {candidate_count} 条候选（{status_text}）。")

            category_history = filter_prompt_history_for_category(task_prompt_history, focused_category)
            recent_debug = category_history[0] if category_history else None
            if recent_debug:
                mode_label = "草稿试跑" if recent_debug.get("mode") == "draft_run" else "当前 vs 草稿"
                st.caption(
                    f"最近调试：{recent_debug.get('created_at', '')} | {mode_label} | 候选 {recent_debug.get('candidate_count', 0)} 条 | "
                    f"{render_history_status('草稿', recent_debug.get('draft_status'), recent_debug.get('draft_selected_count'))}"
                )
                excerpt = recent_debug.get("draft_prompt_excerpt", "").strip()
                if excerpt:
                    st.caption(f"最近草稿摘要：{excerpt}")
            else:
                st.info("这个板块最近还没有调试记录，可以先抓候选再试跑。")
            st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
        st.markdown('<div class="ib-section-title">板块调试</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="ib-section-copy">这里承接原来的 Prompt Debug 能力：抓候选、试跑草稿 Prompt、对比当前与草稿，并在确认后写回任务配置。</div>',
            unsafe_allow_html=True,
        )
        if not selected_task_categories:
            st.info("当前任务还没有板块，先去“任务管理”添加板块和 RSS 源。")
        else:
            debug_task_scope = selected_task_id or "default"
            stored_debug_category = st.session_state.get(f"prompt_debug_category::{debug_task_scope}")
            debug_category = focused_category or stored_debug_category or selected_task_categories[0]
            if debug_category not in selected_task_categories:
                debug_category = selected_task_categories[0]
            set_prompt_debug_category(selected_task_id, debug_category)

            debug_category = st.selectbox(
                "调试板块",
                options=selected_task_categories,
                index=selected_task_categories.index(debug_category),
                key=f"inline_prompt_debug_category::{debug_task_scope}",
            )
            set_prompt_debug_category(selected_task_id, debug_category)

            saved_prompt = selected_task_feeds.get(debug_category, {}).get("prompt", "")
            draft_key = f"draft_prompt::{debug_task_scope}::{debug_category}"
            if draft_key not in st.session_state:
                st.session_state[draft_key] = saved_prompt
            draft_prompt = st.text_area(
                "草稿 Prompt",
                value=st.session_state[draft_key],
                height=180,
                key=draft_key,
            ).strip()

            debug_selection = get_selection_settings(selected_task_runtime_config)
            st.caption(
                f"当前筛选规则：最多保留 {debug_selection['max_selected_items']} 条 | 标题 {debug_selection['title_max_len']} 字 | "
                f"摘要 {debug_selection['summary_max_len']} 字 | 分批大小 {debug_selection['batch_size']}"
            )

            debug_meta = st.session_state.get("prompt_debug_meta", {})
            candidate_list = st.session_state.get("prompt_debug_candidates", [])
            candidate_matches = (
                debug_meta.get("task_id") == selected_task_id
                and debug_meta.get("category") == debug_category
            )
            debug_candidates = candidate_list if candidate_matches else []
            using_fallback_candidates = bool(debug_meta.get("using_fallback")) if candidate_matches else False
            prompt_changed = draft_prompt != saved_prompt

            debug_action1, debug_action2, debug_action3, debug_action4 = st.columns(4)
            with debug_action1:
                if st.button("📥 抓候选", key=f"inline_fetch_candidates::{debug_category}", use_container_width=True):
                    candidate_count, using_fallback = seed_prompt_debug_candidates(selected_task_id, debug_category)
                    status_text = "内置样例" if using_fallback else "真实 RSS"
                    st.success(f"已为 [{debug_category}] 准备 {candidate_count} 条候选（{status_text}）。")
                    st.rerun()
            with debug_action2:
                if st.button("🧪 试跑草稿", key=f"inline_draft_run::{debug_category}", use_container_width=True):
                    if not debug_candidates:
                        st.warning("请先抓取候选，再试跑草稿 Prompt。")
                    else:
                        ui_logger = build_ui_logger()
                        result = run_prompt_debug(
                            config=selected_task_runtime_config,
                            category_name=debug_category,
                            news_list=debug_candidates,
                            category_prompt=draft_prompt,
                            logger=ui_logger,
                        )
                        st.session_state["prompt_debug_result"] = {
                            "category": debug_category,
                            "result": result,
                        }
                        st.session_state.pop("prompt_debug_compare", None)
                        append_prompt_debug_history(
                            bot_dir,
                            make_draft_run_record(
                                task_id=selected_task_id,
                                task_name=selected_task.get("name", selected_task_id) if selected_task else selected_task_id,
                                category=debug_category,
                                candidate_count=len(debug_candidates),
                                result=result,
                                using_fallback_candidates=using_fallback_candidates,
                                draft_prompt=draft_prompt,
                            ),
                        )
                        st.success("草稿 Prompt 试跑完成。")
                        st.rerun()
            with debug_action3:
                if st.button("🆚 当前 vs 草稿", key=f"inline_compare_run::{debug_category}", use_container_width=True):
                    if not debug_candidates:
                        st.warning("请先抓取候选，再比较当前与草稿 Prompt。")
                    else:
                        ui_logger = build_ui_logger()
                        saved_result = run_prompt_debug(
                            config=selected_task_runtime_config,
                            category_name=debug_category,
                            news_list=debug_candidates,
                            category_prompt=saved_prompt,
                            logger=ui_logger,
                        )
                        draft_result = run_prompt_debug(
                            config=selected_task_runtime_config,
                            category_name=debug_category,
                            news_list=debug_candidates,
                            category_prompt=draft_prompt,
                            logger=ui_logger,
                        )
                        st.session_state["prompt_debug_compare"] = {
                            "category": debug_category,
                            "saved_result": saved_result,
                            "draft_result": draft_result,
                        }
                        st.session_state.pop("prompt_debug_result", None)
                        append_prompt_debug_history(
                            bot_dir,
                            make_compare_record(
                                task_id=selected_task_id,
                                task_name=selected_task.get("name", selected_task_id) if selected_task else selected_task_id,
                                category=debug_category,
                                candidate_count=len(debug_candidates),
                                saved_result=saved_result,
                                draft_result=draft_result,
                                using_fallback_candidates=using_fallback_candidates,
                                draft_prompt=draft_prompt,
                            ),
                        )
                        st.success("当前 Prompt 与草稿 Prompt 对比完成。")
                        st.rerun()
            with debug_action4:
                if st.button("💾 写回草稿到任务", key=f"inline_writeback::{debug_category}", use_container_width=True):
                    tasks_data = get_tasks_data()
                    task_def = deepcopy(tasks_data.get("tasks", {}).get(selected_task_id, {}))
                    task_def.setdefault("feeds", {}).setdefault(debug_category, {}).update(
                        {**task_def.get("feeds", {}).get(debug_category, {}), "prompt": draft_prompt}
                    )
                    save_task_definition(selected_task_id, task_def)
                    st.success(f"已把 [{debug_category}] 的草稿 Prompt 写回任务配置。")
                    st.rerun()

            if debug_candidates:
                render_kpi_strip(
                    candidate_count=len(debug_candidates),
                    selected_count=len((st.session_state.get("prompt_debug_result", {}).get("result") or {}).get("selected_items", []))
                    if st.session_state.get("prompt_debug_result", {}).get("category") == debug_category
                    else len((st.session_state.get("prompt_debug_compare", {}).get("draft_result") or {}).get("selected_items", []))
                    if st.session_state.get("prompt_debug_compare", {}).get("category") == debug_category
                    else 0,
                    using_fallback=using_fallback_candidates,
                    prompt_changed=prompt_changed,
                )
                with st.expander(f"候选池预览（{len(debug_candidates)} 条）", expanded=False):
                    for idx, item in enumerate(debug_candidates[:20], start=1):
                        st.markdown(f"**{idx}. [{item.get('title', '')}]({item.get('link', '')})**")
                        st.caption(item.get("summary", "") or "无摘要")
                    if len(debug_candidates) > 20:
                        st.caption(f"其余 {len(debug_candidates) - 20} 条已省略。")
            else:
                st.info("当前还没有候选内容。先抓取一批候选，再试跑草稿或做对比。")

            single_result = st.session_state.get("prompt_debug_result", {})
            if single_result.get("category") == debug_category and single_result.get("result"):
                render_result_panel(title="草稿试跑结果", result=single_result["result"])

            compare_result = st.session_state.get("prompt_debug_compare", {})
            if compare_result.get("category") == debug_category:
                compare_col1, compare_col2 = st.columns(2)
                with compare_col1:
                    render_result_panel(title="当前 Prompt", result=compare_result.get("saved_result", {}))
                with compare_col2:
                    render_result_panel(title="草稿 Prompt", result=compare_result.get("draft_result", {}))

            inline_history = filter_prompt_history_for_category(task_prompt_history, debug_category)
            if inline_history:
                st.markdown("**最近调试记录**")
                for item in inline_history[:5]:
                    mode_label = "草稿试跑" if item.get("mode") == "draft_run" else "当前 vs 草稿"
                    st.markdown(
                        f"- {item.get('created_at', '')} | {mode_label} | 候选 {item.get('candidate_count', 0)} 条 | "
                        f"{render_history_status('草稿', item.get('draft_status'), item.get('draft_selected_count'))}"
                    )
            else:
                st.caption("当前板块还没有调试历史。")
        st.markdown("</div>", unsafe_allow_html=True)

        header_col1, header_col2, header_col3 = st.columns([1.3, 1.0, 1.2])
        with header_col1:
            if st.button("🔄 立即刷新健康度", type="primary", use_container_width=True):
                with st.spinner("正在全量检查 RSS 源，请稍候..."):
                    health_snapshot = get_feed_health_snapshot(
                        selected_task_feeds,
                        bot_dir=bot_dir,
                        use_cache=False,
                        force_refresh=True,
                    )
                    save_task_health(health_snapshot, selected_task_id, bot_dir)
                    selected_task_state = touch_revalidation_state(
                        task_id=selected_task_id,
                        config_revision=selected_task_state.get("config_revision", current_revision),
                        needs_revalidation=False,
                        bot_dir=bot_dir,
                        last_validated_revision=selected_task_state.get("config_revision", current_revision),
                    )
                st.success("RSS 健康度已刷新。")
        with header_col2:
            only_problem_feeds = st.toggle("仅看异常/无更新", value=False)
        with header_col3:
            stale_7d_only = st.toggle("仅看 7 天未更新", value=False)

        if health_snapshot is None:
            st.info("当前还没有健康度缓存。点击“立即刷新健康度”后，控制台会生成第一份检查结果。")
        else:
            if selected_task_state.get("needs_revalidation"):
                st.warning("当前健康快照可能与最新配置不一致，建议先点“立即刷新健康度”。")
            diagnosis_cards = build_no_push_diagnosis(
                health_snapshot=health_snapshot,
                run_summary=run_summary,
                configured_categories=selected_task_categories,
            )
            if focused_category:
                diagnosis_cards = [
                    card for card in diagnosis_cards
                    if any(item.get("category") == focused_category for item in card.get("details", []) if isinstance(item, dict))
                ]
            if diagnosis_cards:
                st.markdown('<div class="ib-hero">', unsafe_allow_html=True)
                st.markdown('<div class="ib-eyebrow">No Push Diagnosis</div>', unsafe_allow_html=True)
                st.markdown('<div class="ib-title">为什么今天没推送？</div>', unsafe_allow_html=True)
                task_started = run_summary.get("task_started_at")
                task_copy = f"最近一次任务开始于 {task_started}。" if task_started else "已根据最近一次任务日志和当前健康度缓存生成诊断。"
                st.markdown(
                    f'<div class="ib-subtitle">当前查看任务：{active_task_name}（{selected_task_id or "未选择"}）<br/>{task_copy} 以下卡片按优先级排序，先处理靠前问题。</div>',
                    unsafe_allow_html=True,
                )
                st.markdown("</div>", unsafe_allow_html=True)
                for card in diagnosis_cards:
                    render_diagnosis_card(
                        card,
                        prompt_categories=selected_task_categories,
                        key_prefix="health",
                    )

            checked_at = health_snapshot.get("checked_at")
            age_text = summarize_cache_age(health_snapshot.get("cache_age_seconds"))
            source_label = "缓存结果" if health_snapshot.get("source") == "cache" else "刚刚刷新"
            if health_snapshot.get("is_stale"):
                st.warning(
                    f"当前展示的是缓存结果，检查时间 {format_timestamp(checked_at)}，缓存年龄约 {age_text}，已超过 {CACHE_TTL_SECONDS // 60} 分钟。"
                )
            else:
                st.caption(
                    f"检查时间：{format_timestamp(checked_at)} | 数据来源：{source_label} | 缓存年龄：{age_text} | 缓存文件：{task_health_cache_file_path(selected_task_id, bot_dir)}"
                )

            counts = health_snapshot.get("counts", {})
            error_types = health_snapshot.get("error_types", {})
            st.markdown(
                f"""
                <div class="ib-kpi-grid">
                  <div class="ib-kpi-card">
                    <div class="ib-kpi-label">正常源</div>
                    <div class="ib-kpi-value">{counts.get('ok', 0)}</div>
                  </div>
                  <div class="ib-kpi-card">
                    <div class="ib-kpi-label">无更新</div>
                    <div class="ib-kpi-value">{counts.get('stale', 0)}</div>
                  </div>
                  <div class="ib-kpi-card">
                    <div class="ib-kpi-label">错误源</div>
                    <div class="ib-kpi-value">{counts.get('error', 0)}</div>
                  </div>
                  <div class="ib-kpi-card">
                    <div class="ib-kpi-label">错误类型分布</div>
                    <div class="ib-kpi-value" style="font-size:1.0rem;">{", ".join(f"{k}:{v}" for k, v in error_types.items()) or "无"}</div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            for category_result in health_snapshot.get("categories", []):
                if focused_category and category_result.get("category") != focused_category:
                    continue
                visible_feeds = []
                for feed in category_result.get("feeds", []):
                    latest_pub = feed.get("latest_pub")
                    older_than_7d = False
                    if latest_pub:
                        try:
                            older_than_7d = (datetime.now() - datetime.fromisoformat(latest_pub)).days >= 7
                        except ValueError:
                            older_than_7d = False

                    if only_problem_feeds and feed.get("status") == "ok":
                        continue
                    if stale_7d_only and not (feed.get("status") == "stale" and older_than_7d):
                        continue
                    visible_feeds.append(feed)

                if not visible_feeds:
                    continue

                category_counts = category_result.get("counts", {})
                st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
                st.markdown(
                    f"""
                    <div class="ib-section-title">{category_result['category']}</div>
                    <div class="ib-chip-row">
                      <span class="ib-chip ib-chip-success">正常 {category_counts.get('ok', 0)}</span>
                      <span class="ib-chip ib-chip-warning">无更新 {category_counts.get('stale', 0)}</span>
                      <span class="ib-chip ib-chip-error">错误 {category_counts.get('error', 0)}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                for feed in visible_feeds:
                    st.markdown(
                        f"""
                        <div class="ib-panel" style="margin-top:12px; margin-bottom:0;">
                          <div class="ib-chip-row">{render_health_chip(feed.get('status', 'unknown'))}</div>
                          <div style="font-weight:700; margin:8px 0 6px;">{feed.get('url', '')}</div>
                          <div class="ib-section-copy" style="margin-bottom:6px;">
                            近 24h: {feed.get('recent_entries', 0)} 条 | 总条数: {feed.get('total_entries', 0)} | 最近发布时间: {format_timestamp(feed.get('latest_pub'))}
                          </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    if feed.get("status") == "error":
                        st.error(f"{feed.get('error_type', 'unknown_error')}: {feed.get('error_message', '未知错误')}")
                    else:
                        elapsed = feed.get("elapsed_s")
                        if elapsed is not None:
                            st.caption(f"响应耗时：{elapsed}s")
                st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
        st.markdown('<div class="ib-section-title">最近相关日志</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="ib-section-copy">这里保留当前任务最近一段相关日志作为补充证据；如果还不够，再去完整日志页深挖。</div>',
            unsafe_allow_html=True,
        )
        recent_log_excerpt = load_recent_log_excerpt()
        if recent_log_excerpt:
            st.code(recent_log_excerpt, language="bash")
        else:
            st.info("当前还没有相关日志。")
        st.markdown("</div>", unsafe_allow_html=True)

    with tab4:
        st.subheader("🕵️‍♂️ 深度运行日志追踪")
        st.caption("日志已开启企业级轮转模式（自动保留 30 天，每日切割）。默认优先展示当前任务相关日志，便于快速排查。")
        active_task_name = selected_task.get("name", selected_task_id) if selected_task_id else "未选择任务"
        st.markdown(
            f'<div class="ib-chip-row"><span class="ib-chip ib-chip-neutral">当前任务: {active_task_name}</span>'
            f'<span class="ib-chip ib-chip-neutral">任务 ID: {selected_task_id or "未选择"}</span></div>',
            unsafe_allow_html=True,
        )

        col_1, col_2, col_3 = st.columns([6, 1.5, 1.5])
        with col_2:
            if st.button("🔄 刷新日志追踪"):
                st.rerun()
        with col_3:
            if os.path.exists(bot_log_path):
                with open(bot_log_path, "r", encoding="utf-8") as f:
                    log_data = f.read()
                st.download_button(
                    label="📥 下载完整日志",
                    data=log_data,
                    file_name=f"mia_bot_{datetime.now().strftime('%Y%m%d')}.log",
                    mime="text/plain",
                )

        if os.path.exists(bot_log_path):
            try:
                with open(bot_log_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                    filtered_lines = filter_log_lines_for_task(lines, selected_task_id)
                    last_lines = "".join(lines[-300:])
                    last_filtered_lines = "".join(filtered_lines[-180:])
                if selected_task_id:
                    st.markdown("**当前任务相关日志**")
                    st.code(last_filtered_lines or "当前日志中还没有匹配该任务 ID 的记录。", language="bash")
                    st.markdown("**最近全量日志**")
                st.code(last_lines, language="bash")
            except Exception as e:
                st.error(f"读取日志出错: {e}")
        else:
            st.info("暂无深度日志。请点击侧边栏【立即手动运行】生成第一份报告。")

    with tab5:
        st.subheader("推送版式与开关")
        settings = config["settings"]

        settings["report_title"] = st.text_input(
            "早报大标题 ({date} 会自动替换为当天日期)",
            value=settings.get("report_title", "📅 营销情报早报 | {date}"),
        )
        settings["empty_message"] = st.text_input(
            "无更新时的提示语", value=settings.get("empty_message", "📭 今日全网无重要更新。")
        )

        st.divider()
        settings["show_footer"] = st.toggle("显示底部控制台链接", value=settings.get("show_footer", True))
        if settings["show_footer"]:
            settings["footer_text"] = st.text_input(
                "底部链接文字及URL", value=settings.get("footer_text", "👀 [前往控制台调整策略](http://你的IP:8501)")
            )

        if st.button("💾 保存版式设置"):
            config["settings"] = settings
            save_config(config)
            mark_tasks_changed(list(get_tasks_data().get("tasks", {}).keys()))
            st.toast("设置已生效！")

    with tab6:
        st.subheader("🔬 任务调试")
        st.caption("选择任务并运行 Dry Run — 仅在面板展示结果，不发送任何频道消息。")

        tasks_data = load_tasks(bot_dir)
        tasks = tasks_data.get("tasks", {})
        task_ids = list(tasks.keys())

        if not task_ids:
            st.warning("暂无任务，请先在「📋 任务管理」创建任务。")
        else:
            selected = st.selectbox(
                "选择任务",
                options=task_ids,
                index=task_ids.index(selected_task_id) if selected_task_id in task_ids else 0,
            )

            col_run, col_info = st.columns([1, 3])
            with col_run:
                dry_run = st.button("🔬 Dry Run", type="primary", use_container_width=True)

            task_def = tasks.get(selected, {})
            st.markdown(f"**Pipeline**: `{task_def.get('pipeline', 'editorial')}`")
            st.markdown(f"**频道**: `{', '.join(task_def.get('channels', []))}`")
            sched = task_def.get("schedule", {})
            st.markdown(f"**调度**: {sched.get('hour', 8):02d}:{sched.get('minute', 0):02d}")

            if dry_run:
                ui_logger = build_ui_logger()
                with st.spinner(f"正在 Dry Run 任务「{selected}」..."):
                    try:
                        result = scheduler.run_task_by_id(selected, dry_run=True)
                    except Exception as e:
                        result = {"ok": False, "error": str(e)}

                st.session_state["task_debug_result"] = {
                    **result,
                    "_selected_task_id": selected,
                    "_selected_task_name": task_def.get("name", selected),
                }

            if "task_debug_result" in st.session_state:
                result = st.session_state["task_debug_result"]
                result_task_id = result.get("_selected_task_id")
                result_task_name = result.get("_selected_task_name", result_task_id)
                if result_task_id == selected:
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

                    with st.expander("🔬 完整中间结果"):
                        st.json({
                            "ok": result.get("ok"),
                            "pipeline": result.get("pipeline"),
                            "dry_run": result.get("dry_run"),
                            "task_id": result.get("task_id"),
                            "task_name": result_task_name,
                            "error": result.get("error"),
                            "channel_results": result.get("channel_results", []),
                        }, expanded=False)
                else:
                    st.info(f"当前保存的是任务「{result_task_name}」的 Dry Run 结果；切回对应任务可查看详情。")


if __name__ == "__main__":
    main()
