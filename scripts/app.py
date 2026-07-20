import json
import logging
import mimetypes
import os
from copy import deepcopy
from datetime import datetime

import streamlit as st

# Defense in depth for static Content-Type: Streamlit can serve
# /app/static/** without ever running this script (no session), so the
# authoritative fix is the deploy step ensuring the host's /etc/mime.types;
# registering here too covers mime maps initialized after a session starts.
mimetypes.add_type("text/html", ".html")
mimetypes.add_type("image/jpeg", ".jpg")
mimetypes.add_type("image/jpeg", ".jpeg")
mimetypes.add_type("image/png", ".png")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("image/gif", ".gif")

from insightbot.channels import init_channels, test_channel_config, validate_channel_definition
from insightbot.config import (
    load_channels,
    load_runtime_config,
    load_tasks,
    load_tasks_config,
    normalize_task_definition,
    save_channels,
    save_tasks,
)
from insightbot.feed_health import CACHE_TTL_SECONDS, describe_feed_issue, get_feed_health_snapshot, load_health_cache
from insightbot.ids import is_safe_id
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
    make_draft_run_record,
)
from insightbot.product import build_change_proposal, build_task_card
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
try:
    from scripts.ui.dry_run import _command_result_to_ui_result, render_inline_dry_run_panel, render_task_run_result
    from scripts.ui.overview import render_task_overview
    from scripts.ui.task_config import render_task_empty_state_wizard
    from scripts.ui.workbench_layout import (
        bordered_section,
        render_page_map,
        render_section_heading,
        render_section_note,
        render_workbench_styles,
    )
except ModuleNotFoundError:
    from ui.dry_run import _command_result_to_ui_result, render_inline_dry_run_panel, render_task_run_result
    from ui.overview import render_task_overview
    from ui.task_config import render_task_empty_state_wizard
    from ui.workbench_layout import (
        bordered_section,
        render_page_map,
        render_section_heading,
        render_section_note,
        render_workbench_styles,
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

    def split_feed_url_and_name(raw_value: str) -> tuple[str, str]:
        raw_text = str(raw_value or "").strip()
        if " # " in raw_text:
            base_url, _, display_name = raw_text.partition(" # ")
            return base_url.strip(), display_name.strip()
        return raw_text, ""

    def compose_feed_url_and_name(feed_url: str, feed_name: str) -> str:
        normalized_url = str(feed_url or "").strip()
        normalized_name = str(feed_name or "").strip()
        if not normalized_url:
            return ""
        return f"{normalized_url} # {normalized_name}" if normalized_name else normalized_url

    def get_source_display_name(source: dict, fallback: str) -> str:
        _, feed_name = split_feed_url_and_name(source.get("url", ""))
        return feed_name or fallback

    PIPELINE_LABELS = {
        "editorial": "智能编辑流程（推荐）",
        "classic": "传统规则流程",
    }
    SEARCH_PROVIDER_LABELS = {
        "baidu": "百度搜索",
        "duckduckgo": "DuckDuckGo 搜索",
        "brave": "Brave Search",
        "bocha": "博查搜索",
    }
    CHANNEL_TYPE_LABELS = {
        "wecom": "企业微信机器人",
        "feishu_app": "飞书应用消息",
        "feishu_bot": "飞书自定义机器人",
    }
    RECEIVE_ID_TYPE_LABELS = {
        "chat_id": "飞书群聊 ID",
        "open_id": "用户 Open ID",
        "user_id": "用户 ID",
        "union_id": "用户 Union ID",
        "email": "邮箱",
    }
    MESSAGE_TEMPLATE_LABELS = {
        "interactive": "飞书卡片消息",
        "text": "普通文本消息",
    }

    def label_for(mapping: dict):
        return lambda value: mapping.get(value, value)

    def format_channel_option(channel_id: str, channel_payloads: dict) -> str:
        channel = (channel_payloads.get("channels", {}) or {}).get(channel_id, {})
        name = channel.get("name") or channel_id
        channel_type = CHANNEL_TYPE_LABELS.get(channel.get("type", ""), channel.get("type", "未指定类型"))
        return f"{name}（{channel_type}）"

    def summarize_task_debug_result(result: dict) -> dict:
        stage_results = result.get("stage_results", {}) if isinstance(result, dict) else {}
        assignment_map = stage_results.get("assignment_result", {}).get("category_candidate_map", {})
        category_results = stage_results.get("category_results", {})

        return {
            "global_candidates": len(stage_results.get("global_candidates", []) or []),
            "screened_candidates": len(stage_results.get("screened_result", {}).get("screened", []) or []),
            "unassigned_candidates": len(stage_results.get("assignment_result", {}).get("unassigned", []) or []),
            "assigned_by_category": {
                key: len(value or [])
                for key, value in assignment_map.items()
            },
            "selected_by_category": {
                key: len((value or {}).get("selected_items", []) or [])
                for key, value in category_results.items()
                if isinstance(value, dict)
            },
        }

    def get_channel_reference_tasks(channel_id: str) -> list[str]:
        tasks_data = get_tasks_data()
        referenced = []
        for task_id, task_def in tasks_data.get("tasks", {}).items():
            if channel_id in (task_def.get("channels", []) or []):
                referenced.append(task_def.get("name", task_id))
        return referenced

    def render_channel_validation(channel_id: str, channel_payload: dict) -> None:
        validation = validate_channel_definition(channel_id, channel_payload)
        referenced_tasks = get_channel_reference_tasks(channel_id)

        if validation["is_ready"]:
            st.success("✅ 当前频道配置完整，可用于真实发送。")
        else:
            st.warning("⚠️ 当前频道配置未完成，真实发送或测试可能失败。")
            for issue in validation["issues"]:
                st.caption(f"- {issue['message']}")

        if referenced_tasks:
            st.caption("当前引用任务：" + "、".join(referenced_tasks))
        else:
            st.caption("当前没有任务引用这个频道。")

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
        section_count = summary.get("section_count", summary.get("category_count", 0))
        rss_source_count = summary.get("rss_source_count", summary.get("feed_count", 0))
        task_version_id = summary.get("task_version_id") or (validation_result.get("task_version") or {}).get("version_id")
        st.caption(
            f"板块 {section_count} 个 | RSS {rss_source_count} 个 | "
            f"频道 {summary.get('channel_count', 0)} 个 | 调度 {'已配置' if summary.get('has_schedule') else '未配置'}"
        )
        if task_version_id:
            st.caption(f"Domain Kernel: `{task_version_id}` | Diagnosis: `{summary.get('domain_diagnosis_id', 'n/a')}`")
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
        if validation_result.get("domain_diagnosis"):
            with st.expander("开发者详情：Domain Diagnosis", expanded=False):
                st.json(validation_result["domain_diagnosis"], expanded=False)
        changeset = st.session_state.get(f"last_changeset::{validation_result.get('task_id')}")
        if changeset:
            with st.expander("最近一次配置 ChangeSet", expanded=False):
                st.json(changeset, expanded=False)
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
            st.caption("建议切到 Investigate 查看完整错误上下文。")

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
        try:
            tasks_data = load_tasks(bot_dir)
        except Exception:
            # Broken tasks.json: stay alive with an empty task list; the
            # scheduler.config_error banner above explains the failure.
            return {"tasks": {}}
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

    def save_task_definition(
        task_id: str,
        task_def: dict,
        *,
        intent: str = "Update task definition from Streamlit UI",
        rationale: str = "User changed task configuration in the workbench.",
    ) -> bool:
        tasks_data = get_tasks_data()
        tasks_data.setdefault("tasks", {})
        normalized_task = normalize_task_definition(task_def)
        try:
            changeset = scheduler.propose_task_changeset_command(
                task_id,
                normalized_task,
                intent=intent,
                rationale=rationale,
            )
            current_validation = build_task_validation(task_id, tasks_data.get("tasks", {}).get(task_id, {}))
            current_version_id = current_validation.get("summary", {}).get("task_version_id")
            st.session_state[f"pending_changeset::{task_id}"] = {
                "changeset": changeset.to_dict(),
                "proposal": build_change_proposal(changeset, current_version_id=current_version_id),
                "config": None,
                "secrets": None,
                "task_name": normalized_task.get("name", task_id),
            }
            return True
        except Exception as exc:
            logging.getLogger("InsightBot").warning(
                "Domain ChangeSet proposal failed for task '%s': %s",
                task_id,
                exc,
            )
            st.error(f"生成变更提案失败：{exc}")
            return False

    def build_task_runtime_config(task_id: str | None) -> dict:
        if not task_id:
            return runtime_config
        try:
            return load_tasks_config(task_id, bot_dir)
        except Exception:
            return runtime_config

    def add_rss_feed_to_task(task_id: str, category: str, feed_url: str, feed_name: str = "") -> bool:
        """Add a single RSS feed into a task section."""
        try:
            tasks_data = get_tasks_data()
            task_def = normalize_task_definition(deepcopy(tasks_data["tasks"].get(task_id, {})))
            task_sources = task_def.setdefault("sources", {})
            task_sections = task_def.setdefault("sections", {})
            task_sections.setdefault(category, {"prompt": "", "keywords": [], "source_hints": [category]})
            rss_sources = list(task_sources.get("rss", []) or [])

            existing_urls = [
                str(item.get("url", "")).split(" # ")[0].strip()
                for item in rss_sources
                if isinstance(item, dict)
            ]
            if feed_url in existing_urls:
                return False

            entry = compose_feed_url_and_name(feed_url, feed_name)
            rss_sources.append(
                {
                    "id": f"source_{len(rss_sources) + 1}",
                    "url": entry,
                    "enabled": True,
                    "tags": [category],
                    "section_hints": [category],
                }
            )
            task_sources["rss"] = rss_sources
            return save_task_definition(
                task_id,
                task_def,
                intent="Add RSS source from Workbench",
                rationale=f"User requested adding RSS source {feed_url} to {category}.",
            )
        except Exception as e:
            st.error(f"淇濆瓨澶辫触: {e}")
            return False

    def get_task_sections(task_def: dict | None) -> dict:
        normalized = normalize_task_definition(task_def or {})
        return deepcopy(normalized.get("sections", {}))

    def get_task_sources(task_def: dict | None) -> dict:
        normalized = normalize_task_definition(task_def or {})
        return deepcopy(normalized.get("sources", {}))

    config = load_config()
    runtime_config = load_runtime_view()

    # Load tasks and channels; create scheduler (auto-migrates v1 config if needed)
    channels_data = load_channels(bot_dir)
    init_channels(channels_data)
    scheduler = create_scheduler(bot_dir)
    tasks_data = get_tasks_data()

    def build_task_validation(task_id: str | None, task_def: dict | None) -> dict:
        if not task_id or not task_def:
            return {"status": "not_ready", "is_runnable": False, "issues": [], "summary": {}}
        if hasattr(scheduler, "validate_task_command"):
            try:
                return scheduler.validate_task_command(task_id)
            except Exception as exc:
                logging.getLogger("InsightBot").warning(
                    "Domain validation failed for task '%s'; falling back to legacy validation: %s",
                    task_id,
                    exc,
                )
        return validate_task_definition(task_id, task_def, load_channels(bot_dir))

    selected_task_id, selected_task = get_selected_task(tasks_data)
    selected_task_runtime_config = build_task_runtime_config(selected_task_id)
    selected_task_feeds = deepcopy(selected_task_runtime_config.get("feeds", {})) if selected_task else {}
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
    selected_task_validation = build_task_validation(selected_task_id, selected_task)

    st.set_page_config(page_title="营销情报站 | 控制台", layout="wide")
    render_prompt_debug_styles()
    render_workbench_styles()
    st.title("InsightBot | Insight Workbench")
    st.caption(f"当前编辑配置文件: {active_edit_path}")

    if getattr(scheduler, "config_error", None):
        st.error(
            "⚠️ tasks.json 加载失败，已保留修复前的运行状态；修复文件后调度器会自动恢复。\n\n"
            f"错误详情：`{scheduler.config_error}`"
        )

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
            selected_task_feeds = deepcopy(selected_task_runtime_config.get("feeds", {}))
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
            selected_task_validation = build_task_validation(selected_task_id, selected_task)
            selected_pipeline_label = PIPELINE_LABELS.get(
                selected_task.get("pipeline", "editorial"),
                selected_task.get("pipeline", "editorial"),
            )
            st.caption(
                f"生成流程：{selected_pipeline_label} | "
                f"频道：{len(selected_task.get('channels', []))} 个 | "
                f"栏目：{len(selected_task_categories)} 个"
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
                "生成流程",
                options=["editorial", "classic"],
                index=0,
                key="quick_create_task_pipeline",
                format_func=label_for(PIPELINE_LABELS),
            )
        with quick_col2:
            quick_new_task_hour = st.number_input("小时", 0, 23, 8, key="quick_create_task_hour")
        with quick_col3:
            quick_new_task_min = st.number_input("分钟", 0, 59, 0, key="quick_create_task_min")

        if st.button("创建任务", key="quick_create_task_btn", use_container_width=True):
            tasks_data = get_tasks_data()
            tasks = tasks_data.get("tasks", {})
            if quick_new_task_id and not is_safe_id(quick_new_task_id):
                st.error("任务 ID 只能使用英文字母、数字、下划线和连字符，长度 1-64。")
            elif quick_new_task_id and quick_new_task_id not in tasks:
                new_task_def = {
                    "name": quick_new_task_name or quick_new_task_id,
                    "enabled": False,
                    "pipeline": quick_new_task_pipeline,
                    "sources": deepcopy(get_task_sources(selected_task)),
                    "sections": deepcopy(get_task_sections(selected_task)),
                    "pipeline_config": deepcopy(get_editorial_defaults()),
                    "channels": deepcopy((selected_task or {}).get("channels", [])),
                    "schedule": {"hour": int(quick_new_task_hour), "minute": int(quick_new_task_min)},
                }
                if hasattr(scheduler, "create_task_command"):
                    result = scheduler.create_task_command(
                        quick_new_task_id,
                        new_task_def,
                        intent="Create task from Streamlit quick action",
                        rationale="User created a task in the sidebar quick action.",
                    )
                    if not result.ok:
                        st.error(result.error or "创建任务失败")
                        st.stop()
                    else:
                        st.session_state[f"last_changeset::{quick_new_task_id}"] = result.changeset.to_dict() if result.changeset else None
                else:
                    tasks[quick_new_task_id] = new_task_def
                    save_tasks(tasks_data, bot_dir)
                    scheduler.reload()
                mark_task_changed(quick_new_task_id)
                st.session_state["selected_task_id"] = quick_new_task_id
                st.success(f"任务「{quick_new_task_id}」已创建。")
                st.rerun()
            elif quick_new_task_id in tasks:
                st.error("任务 ID 已存在。")

        if st.button("准备 Run & Send 确认", type="primary", use_container_width=True, disabled=not bool(selected_task_id)):
            latest_run_for_approval = get_latest_run(selected_task_id, bot_dir) if selected_task_id else None
            approval_card = build_task_card(
                selected_task_spec,
                selected_task_validation,
                latest_run_for_approval,
                get_latest_successful_send(selected_task_id, bot_dir) if selected_task_id else None,
                load_task_health(selected_task_id, bot_dir) if selected_task_id else None,
            )
            st.session_state[f"pending_send::{selected_task_id}"] = {
                "task_id": selected_task_id,
                "task_name": approval_card.get("name") or selected_task_id,
                "task_version_id": approval_card.get("task_version_id"),
                "channels": approval_card.get("channels") or [],
                "risk_summary": approval_card.get("risk_summary") or {},
                "dry_run_checked": bool(latest_run_for_approval and latest_run_for_approval.get("dry_run")),
                "diagnosis": {},
            }
            st.info("已生成发送确认卡。请到 Today 检查后确认发送。")

        st.divider()
        st.header("⏳ 调度器状态")

        tasks_def = {"tasks": {tid: t.task_def for tid, t in scheduler.tasks.items()}}  # 用调度器内存里的最近良好状态,避免重复读盘
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
        st.header("📡 频道")
        channels_data = load_channels(bot_dir)
        channel_count = len(channels_data.get("channels", {}))
        st.metric("已配置频道", str(channel_count))

        st.caption("在 Configure 里管理频道配置和联通性测试。")

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
    workspace_state = scheduler.build_workspace_state_command(selected_task_id) if hasattr(scheduler, "build_workspace_state_command") else {}
    task_state_label, task_state_class, task_state_copy = derive_task_state(
        selected_task_validation,
        latest_run_record,
        latest_success_record,
        selected_task_state,
    )

    tab_today, tab_investigate, tab_configure = st.tabs([
        "Today",
        "Investigate",
        "Configure",
    ])
    tab0 = tab_today
    tab1 = tab_configure
    tab2 = tab_configure
    tab3 = tab_investigate
    tab4 = tab_investigate
    tab5 = tab_configure

    with tab0:
        render_page_map(
            "本页板块",
            [
                ("✅ 今天判断", "today-decision"),
                ("📤 发送确认", "today-send"),
                ("🧾 最近操作", "today-result"),
                ("🗂️ 运营细节", "today-operations"),
            ],
        )
        if selected_task_id:
            task_card = workspace_state.get("selected_task_card") or build_task_card(
                selected_task_spec,
                selected_task_validation,
                latest_run_record,
                latest_success_record,
                overview_health_snapshot,
            )
            human_diagnosis = workspace_state.get("human_diagnosis") or {}
            st.markdown(
                f"""
                <div id="today-decision" class="ib-panel">
                  <div class="ib-panel-title">✅ 今天能不能推送？</div>
                  <div class="ib-subtitle">当前判断：<b>{task_card.get("status")}</b>。{task_card.get("status_reason")}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            decision_col1, decision_col2, decision_col3, decision_col4 = st.columns([1.1, 1.1, 1.2, 1.4])
            with decision_col1:
                st.metric("当前任务", task_card.get("name") or selected_task_id)
            with decision_col2:
                st.metric("配置版本", task_card.get("task_version_id") or "未生成")
            with decision_col3:
                channel_text = "、".join(
                    format_channel_option(channel_id, channels_data)
                    for channel_id in (task_card.get("channels") or [])
                ) or "未配置"
                st.metric("推送到", channel_text)
            with decision_col4:
                dry_run_state = "已验证" if latest_run_record and latest_run_record.get("dry_run") else "建议先 Dry Run"
                st.metric("发送前检查", dry_run_state)

            risk = task_card.get("risk_summary") or {}
            if risk.get("error_count"):
                st.error("当前有阻断风险：" + "；".join(risk.get("top_messages") or ["请查看 Investigate。"]))
            elif risk.get("warning_count"):
                st.warning("当前有提示风险：" + "；".join(risk.get("top_messages") or ["建议查看 Investigate。"]))
            else:
                st.success(human_diagnosis.get("message") or "未发现阻断风险。")
            if human_diagnosis.get("next_action"):
                st.caption("下一步：" + human_diagnosis["next_action"])

            action_col1, action_col2 = st.columns([1, 1])
            with action_col1:
                if st.button("1. 先 Dry Run（不发送）", key=f"today_dry_run_{selected_task_id}", use_container_width=True):
                    with st.spinner("正在 Dry Run，本次不会发送频道消息..."):
                        try:
                            if use_domain_commands:
                                today_result = _command_result_to_ui_result(scheduler.dry_run_task_command(selected_task_id))
                            else:
                                today_result = scheduler.run_task_by_id(selected_task_id, dry_run=True)
                            st.session_state[f"today_dry_run_result::{selected_task_id}"] = today_result
                            if today_result.get("ok"):
                                st.success("Dry Run 完成。请在 Investigate 查看证据和输出预览。")
                            else:
                                st.error(f"Dry Run 失败：{today_result.get('error') or '未知错误'}")
                        except Exception as exc:
                            st.error(f"Dry Run 失败：{exc}")
            with action_col2:
                run_disabled = bool(selected_task_validation and not selected_task_validation.get("is_runnable", False))
                if st.button("2. 准备发送确认", key=f"today_prepare_send_{selected_task_id}", use_container_width=True, disabled=run_disabled):
                    st.session_state[f"pending_send::{selected_task_id}"] = {
                        "task_id": selected_task_id,
                        "task_name": task_card.get("name") or selected_task_id,
                        "task_version_id": task_card.get("task_version_id"),
                        "channels": task_card.get("channels") or [],
                        "risk_summary": risk,
                        "dry_run_checked": bool(latest_run_record and latest_run_record.get("dry_run")),
                        "diagnosis": human_diagnosis,
                    }
                    st.info("已生成发送确认卡。请检查后再确认发送。")

            st.markdown('<div id="today-send"></div>', unsafe_allow_html=True)
            pending_send = st.session_state.get(f"pending_send::{selected_task_id}")
            if pending_send:
                st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
                st.markdown('<div class="ib-section-title">📤 发送确认卡</div>', unsafe_allow_html=True)
                pending_channel_text = "、".join(
                    format_channel_option(channel_id, channels_data)
                    for channel_id in (pending_send.get("channels") or [])
                ) or "未配置"
                st.caption(
                    f"任务：{pending_send.get('task_name')} | 配置版本：{pending_send.get('task_version_id') or 'unknown'} | "
                    f"频道：{pending_channel_text}"
                )
                if pending_send.get("dry_run_checked"):
                    st.success("最近一次证据来自 Dry Run。")
                else:
                    st.warning("还没有最新 Dry Run 证据；如需降低风险，先 Dry Run。")
                pending_risk = pending_send.get("risk_summary") or {}
                if pending_risk.get("error_count"):
                    st.error("阻断风险：" + "；".join(pending_risk.get("top_messages") or ["请查看 Investigate。"]))
                elif pending_risk.get("warning_count"):
                    st.warning("提示风险：" + "；".join(pending_risk.get("top_messages") or ["建议查看 Investigate。"]))
                else:
                    st.caption((pending_send.get("diagnosis") or {}).get("message") or "未发现阻断风险。")
                send_confirm_col1, send_confirm_col2 = st.columns([1, 1])
                with send_confirm_col1:
                    if st.button("确认发送", key=f"today_confirm_send_{selected_task_id}", use_container_width=True):
                        st.session_state.pop(f"pending_send::{selected_task_id}", None)
                        with st.spinner("正在运行并发送到配置频道..."):
                            try:
                                if use_domain_commands:
                                    send_result = _command_result_to_ui_result(scheduler.run_task_command(selected_task_id))
                                else:
                                    send_result = scheduler.run_task_by_id(selected_task_id, dry_run=False)
                                st.session_state[f"today_send_result::{selected_task_id}"] = send_result
                                if send_result.get("ok"):
                                    st.success("已运行并发送。")
                                else:
                                    st.error(f"发送失败：{send_result.get('error') or '未知错误'}")
                            except Exception as exc:
                                st.error(f"发送失败：{exc}")
                with send_confirm_col2:
                    if st.button("取消发送", key=f"today_cancel_send_{selected_task_id}", use_container_width=True):
                        st.session_state.pop(f"pending_send::{selected_task_id}", None)
                        st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)

            st.markdown('<div id="today-result"></div>', unsafe_allow_html=True)
            today_result = st.session_state.get(f"today_dry_run_result::{selected_task_id}") or st.session_state.get(f"today_send_result::{selected_task_id}")
            if today_result:
                with st.expander("最近一次操作结果", expanded=not bool(today_result.get("ok"))):
                    render_task_run_result(
                        {
                            **today_result,
                            "_selected_task_id": selected_task_id,
                            "_selected_task_name": selected_task.get("name", selected_task_id),
                        },
                        summarize_task_debug_result=summarize_task_debug_result,
                        expanded=not bool(today_result.get("ok")),
                        title_prefix="Today",
                    )
        else:
            st.info("暂无任务。请先进入 Configure 创建任务。")

        st.divider()
        st.markdown('<div id="today-operations"></div>', unsafe_allow_html=True)
        with st.expander("🗂️ 更多运营细节", expanded=False):
            render_task_overview(
                selected_task_id=selected_task_id,
                selected_task=selected_task,
                selected_task_categories=selected_task_categories,
                selected_task_validation=selected_task_validation,
                selected_task_state=selected_task_state,
                latest_run_record=latest_run_record,
                latest_success_record=latest_success_record,
                health_snapshot=overview_health_snapshot,
                run_metrics=overview_run_metrics,
                diagnosis_cards=overview_diagnosis_cards,
                prompt_history=overview_prompt_history,
                task_state_label=task_state_label,
                task_state_class=task_state_class,
                task_state_copy=task_state_copy,
                format_timestamp=format_timestamp,
                render_operating_chip=render_operating_chip,
                render_diagnosis_card=render_diagnosis_card,
                workspace_state=workspace_state,
            )

    # ── Tab 1: 任务管理 ────────────────────────────────────────────────────────
    with tab1:
        st.subheader("Configure / 任务设置")
        st.caption("按顺序完成：任务基本信息 -> 信源 -> 栏目 -> 生成策略 -> 变更确认。日常只需要改前两步，高级项默认折叠。")
        render_page_map(
            "本页板块",
            [
                ("🧾 基本信息", "configure-basics"),
                ("🔗 信源", "configure-sources"),
                ("📂 栏目", "configure-sections"),
                ("🔎 搜索补充", "configure-search"),
                ("🧠 生成策略", "configure-strategy"),
                ("🔐 变更确认", "configure-approval"),
            ],
        )

        tasks = tasks_data.get("tasks", {})
        if not tasks or not selected_task_id:
            st.info("暂没有任务，请先在下方创建。")
        else:
            task_def = normalize_task_definition(deepcopy(tasks.get(selected_task_id, {})))
            render_section_note(
                "配置路径：先确认任务名、时间和频道；再维护信源和栏目；最后生成变更提案，确认后才会写入配置。"
            )
            st.markdown(f"**当前任务：{task_def.get('name', selected_task_id)}**")
            render_task_empty_state_wizard(
                task_id=selected_task_id,
                task_def=task_def,
                validation_result=selected_task_validation,
                channels_data=channels_data,
                save_task_definition=save_task_definition,
                defaults=get_editorial_defaults(),
            )

            render_section_heading(
                "🧾 基本信息：这条任务怎么运行",
                "只放任务名、启用状态、调度、生成流程和目标频道。",
                anchor="configure-basics",
            )
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
                    "生成流程",
                    options=pipeline_options,
                    index=pipeline_options.index(pipeline_value),
                    key=f"task_pipeline_{selected_task_id}",
                    format_func=label_for(PIPELINE_LABELS),
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
                format_func=lambda channel_id: format_channel_option(channel_id, channels_data),
            )

            render_section_heading(
                "📺 大屏:这条任务要不要上电视",
                "开启后每次任务跑完自动生成电视大屏页,无需手改 JSON;页面经 Streamlit 静态服务访问。",
                anchor="configure-screen",
            )
            screen_def = task_def.get("screen", {}) or {}
            screen_col1, screen_col2, screen_col3 = st.columns([1, 1, 1])
            with screen_col1:
                screen_enabled = st.toggle(
                    "启用大屏页",
                    value=bool(screen_def.get("enabled", False)),
                    key=f"task_screen_enabled_{selected_task_id}",
                )
                screen_theme_options = ["auto", "dark", "light"]
                screen_theme_current = screen_def.get("theme", "auto")
                screen_theme = st.selectbox(
                    "主题",
                    options=screen_theme_options,
                    index=screen_theme_options.index(screen_theme_current)
                    if screen_theme_current in screen_theme_options
                    else 0,
                    key=f"task_screen_theme_{selected_task_id}",
                    help="auto 按电视本地时间 7:00-19:00 亮色、其余暗色",
                )
            with screen_col2:
                screen_refresh = st.number_input(
                    "页面刷新(秒)",
                    min_value=30,
                    max_value=3600,
                    value=int(screen_def.get("refresh_seconds", 300) or 300),
                    key=f"task_screen_refresh_{selected_task_id}",
                )
                screen_rotate = st.number_input(
                    "板块轮播(秒)",
                    min_value=5,
                    max_value=300,
                    value=int(screen_def.get("rotate_seconds", 15) or 15),
                    key=f"task_screen_rotate_{selected_task_id}",
                )
            with screen_col3:
                screen_image_rotate = st.number_input(
                    "图片轮播(秒)",
                    min_value=3,
                    max_value=300,
                    value=int(screen_def.get("image_rotate_seconds", 10) or 10),
                    key=f"task_screen_image_rotate_{selected_task_id}",
                )
                screen_title = st.text_input(
                    "刊头标题(可选)",
                    value=str(screen_def.get("title", "") or ""),
                    key=f"task_screen_title_{selected_task_id}",
                    placeholder="留空则使用全局推送标题",
                )
            if screen_enabled:
                st.caption(
                    f"页面地址:`/app/static/screen/{selected_task_id}.html`"
                    f"(网关下为 `/insightbot/app/static/screen/{selected_task_id}.html`);"
                    "所有开屏任务列表见 `/app/static/screen/index.html`"
                )

            render_section_heading(
                "🔗 信源：这条任务从哪里找内容",
                "信源名称面向人显示；RSS URL 是实际抓取地址；栏目 hints 用来提示内容更可能属于哪个板块。",
                anchor="configure-sources",
            )
            sections_editor = deepcopy(task_def.get("sections", {}))
            sources_editor = deepcopy(task_def.get("sources", {}))
            rss_sources = deepcopy(sources_editor.get("rss", []))

            source_to_delete = None
            for idx, source in enumerate(rss_sources):
                source_id = str(source.get("id", f"source_{idx + 1}")).strip() or f"source_{idx + 1}"
                source_url_value, source_name_value = split_feed_url_and_name(source.get("url", ""))
                source_display_name = get_source_display_name(source, source_id)
                with st.expander(f"🔗 {source_display_name}", expanded=False):
                    src_col1, src_col2 = st.columns([1.2, 2.8])
                    with src_col1:
                        source["id"] = st.text_input(
                            "内部 ID",
                            value=source_id,
                            key=f"task_source_id_{selected_task_id}_{idx}",
                        ).strip() or source_id
                        source["enabled"] = st.toggle(
                            "启用",
                            value=bool(source.get("enabled", True)),
                            key=f"task_source_enabled_{selected_task_id}_{idx}",
                        )
                    with src_col2:
                        edited_source_name = st.text_input(
                            "信源名称",
                            value=source_name_value,
                            key=f"task_source_name_{selected_task_id}_{idx}",
                            placeholder="优先显示这个名称；为空时回退到内部 ID",
                        ).strip()
                        edited_source_url = st.text_input(
                            "RSS URL",
                            value=source_url_value,
                            key=f"task_source_url_{selected_task_id}_{idx}",
                        ).strip()
                        source["url"] = compose_feed_url_and_name(edited_source_url, edited_source_name)

                    source["section_hints"] = st.multiselect(
                        "推荐栏目",
                        options=list(sections_editor.keys()),
                        default=[hint for hint in source.get("section_hints", []) if hint in sections_editor],
                        key=f"task_source_hints_{selected_task_id}_{idx}",
                    )
                    # tags is now treated as a legacy compatibility field; keep it aligned with section_hints.
                    source["tags"] = list(source.get("section_hints", []) or [])
                    if st.button("删除信源", key=f"del_task_source_{selected_task_id}_{idx}"):
                        source_to_delete = idx

            if source_to_delete is not None:
                del rss_sources[source_to_delete]
                sources_editor["rss"] = rss_sources
                task_def["sources"] = sources_editor
                if save_task_definition(
                    selected_task_id,
                    task_def,
                    intent="Delete RSS source from Workbench",
                    rationale="User requested deleting a task RSS source.",
                ):
                    st.info("已生成删除信源的变更提案，请在确认卡中应用。")

            add_source_col1, add_source_col2, add_source_col3, add_source_col4 = st.columns([2.3, 1.6, 1.6, 1])
            with add_source_col1:
                new_source_url = st.text_input(
                    "新增 RSS URL",
                    placeholder="https://example.com/feed.xml",
                    key=f"new_task_source_url_{selected_task_id}",
                ).strip()
            with add_source_col2:
                new_source_name = st.text_input(
                    "信源名称（可选）",
                    placeholder="例如：数英网",
                    key=f"new_task_source_name_{selected_task_id}",
                ).strip()
            with add_source_col3:
                new_source_section_hint = st.selectbox(
                    "默认栏目",
                    options=[""] + list(sections_editor.keys()),
                    key=f"new_task_source_section_{selected_task_id}",
                )
            with add_source_col4:
                if st.button("添加信源", key=f"add_task_source_{selected_task_id}", use_container_width=True):
                    if new_source_url:
                        section_hints = [new_source_section_hint] if new_source_section_hint else []
                        rss_sources.append(
                            {
                                "id": f"source_{len(rss_sources) + 1}",
                                "url": compose_feed_url_and_name(new_source_url, new_source_name),
                                "enabled": True,
                                "tags": section_hints,
                                "section_hints": section_hints,
                            }
                        )
                        sources_editor["rss"] = rss_sources
                        task_def["sources"] = sources_editor
                        if save_task_definition(
                            selected_task_id,
                            task_def,
                            intent="Add RSS source from Workbench",
                            rationale=f"User requested adding RSS source {new_source_url}.",
                        ):
                            st.info("已生成添加信源的变更提案，请在确认卡中应用。")

            st.divider()
            render_section_heading(
                "📂 栏目：输出最终会分成哪些板块",
                "栏目 prompt 决定哪些内容会进入这个板块。关键词和 source hints 只是辅助提示，不是硬规则。",
                anchor="configure-sections",
            )
            section_to_delete = None
            for category, section_data in sections_editor.items():
                with st.expander(f"📂 {category}", expanded=False):
                    kw_val = "\n".join(section_data.get("keywords", []))
                    sections_editor[category]["keywords"] = [
                        x.strip()
                        for x in st.text_area(
                            "栏目关键词（每行一个）",
                            value=kw_val,
                            height=90,
                            key=f"task_kw_{selected_task_id}_{category}",
                        ).split("\n")
                        if x.strip()
                    ]
                    hint_text = ",".join(section_data.get("source_hints", []) or [])
                    sections_editor[category]["source_hints"] = [
                        item.strip() for item in st.text_input(
                            "信源提示（逗号分隔）",
                            value=hint_text,
                            key=f"task_source_hint_{selected_task_id}_{category}",
                        ).split(",") if item.strip()
                    ]
                    sections_editor[category]["prompt"] = st.text_area(
                        "栏目筛选 Prompt",
                        value=section_data.get("prompt", ""),
                        height=110,
                        key=f"task_prompt_{selected_task_id}_{category}",
                    ).strip()
                    if st.button("删除栏目", key=f"del_task_cat_{selected_task_id}_{category}"):
                        section_to_delete = category

            if section_to_delete:
                sections_editor.pop(section_to_delete, None)
                task_def["sections"] = sections_editor
                if save_task_definition(
                    selected_task_id,
                    task_def,
                    intent="Delete section from Workbench",
                    rationale=f"User requested deleting section {section_to_delete}.",
                ):
                    st.info(f"已生成删除栏目「{section_to_delete}」的变更提案，请在确认卡中应用。")

            add_cat_col1, add_cat_col2 = st.columns([3, 1])
            with add_cat_col1:
                new_category_name = st.text_input(
                    "新增栏目名称",
                    placeholder="例如：品牌营销动态",
                    key=f"new_task_category_{selected_task_id}",
                )
            with add_cat_col2:
                if st.button("添加栏目", key=f"add_task_category_{selected_task_id}", use_container_width=True):
                    if new_category_name.strip():
                        sections_editor.setdefault(
                            new_category_name.strip(),
                            {"keywords": [], "source_hints": [], "prompt": ""},
                        )
                        task_def["sections"] = sections_editor
                        if save_task_definition(
                            selected_task_id,
                            task_def,
                            intent="Add section from Workbench",
                            rationale=f"User requested adding section {new_category_name.strip()}.",
                        ):
                            st.info(f"已生成添加栏目「{new_category_name.strip()}」的变更提案，请在确认卡中应用。")

            st.divider()
            render_section_heading(
                "🔎 搜索补充：RSS 不够时补一层全网线索",
                "这里配置的是补充搜索，不会替代上面的定向信源。没有明确需要时可以保持关闭。",
                anchor="configure-search",
            )
            search_config = deepcopy((task_def.get("sources", {}) or {}).get("search", {}))
            search_enabled = st.toggle(
                "启用搜索补充",
                value=search_config.get("enabled", False),
                key=f"task_search_enabled_{selected_task_id}",
            )
            search_provider_options = ["baidu", "duckduckgo", "brave", "bocha"]
            search_provider = search_config.get("provider", "baidu")
            if search_provider not in search_provider_options:
                search_provider = "baidu"
            search_provider = st.selectbox(
                "搜索引擎",
                options=search_provider_options,
                index=search_provider_options.index(search_provider),
                key=f"task_search_provider_{selected_task_id}",
                format_func=label_for(SEARCH_PROVIDER_LABELS),
            )

            query_state_key = f"task_search_queries::{selected_task_id}"
            if query_state_key not in st.session_state:
                st.session_state[query_state_key] = deepcopy(search_config.get("queries", []))

            search_queries = st.session_state[query_state_key]
            query_to_delete = None
            for idx, query in enumerate(search_queries):
                q_col1, q_col2, q_col3, q_col4 = st.columns([4, 3, 1, 1])
                with q_col1:
                    query["keywords"] = st.text_input(
                        "关键词",
                        value=query.get("keywords", ""),
                        key=f"task_search_keywords_{selected_task_id}_{idx}",
                        label_visibility="collapsed",
                        placeholder="品牌 AI 营销 新动作",
                    )
                with q_col2:
                    current_hints = query.get("section_hints", [])
                    if isinstance(current_hints, str):
                        current_hints = [current_hints] if current_hints else []
                    elif not isinstance(current_hints, list):
                        legacy_hint = str(query.get("category_hint", "")).strip()
                        current_hints = [legacy_hint] if legacy_hint else []
                    query["section_hints"] = st.multiselect(
                        "栏目 hints",
                        options=list(sections_editor.keys()),
                        default=[hint for hint in current_hints if hint in sections_editor],
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
                if st.button("添加搜索词", key=f"task_search_add_{selected_task_id}", use_container_width=True):
                    search_queries.append({"keywords": "", "section_hints": [], "max_results": 10})
                    st.session_state[query_state_key] = search_queries
                    st.rerun()
            with q_action2:
                if st.button("从栏目关键词派生", key=f"task_search_derive_{selected_task_id}", use_container_width=True):
                    derived_queries = []
                    for category, section_data in sections_editor.items():
                        keywords = [kw.strip() for kw in section_data.get("keywords", []) if kw.strip()]
                        if keywords:
                            derived_queries.append(
                                {"keywords": " ".join(keywords), "section_hints": [category], "max_results": 10}
                            )
                    st.session_state[query_state_key] = derived_queries
                    st.rerun()

            st.divider()
            render_section_heading("🧠 生成策略：AI 怎么筛选和分配", anchor="configure-strategy")
            pipeline_config = deepcopy(task_def.get("pipeline_config", {}))
            editorial_defaults = get_editorial_defaults()
            pipe_col1, pipe_col2, pipe_col3, pipe_col4 = st.columns(4)
            with pipe_col1:
                pipeline_config["global_shortlist_multiplier"] = st.slider(
                    "候选放大倍率",
                    min_value=1,
                    max_value=8,
                    value=int(pipeline_config.get("global_shortlist_multiplier", editorial_defaults["global_shortlist_multiplier"])),
                    key=f"task_pipe_multiplier_{selected_task_id}",
                )
            with pipe_col2:
                pipeline_config["assignment_batch_size"] = st.slider(
                    "板块分配批大小",
                    min_value=5,
                    max_value=40,
                    value=int(pipeline_config.get("assignment_batch_size", editorial_defaults["assignment_batch_size"])),
                    key=f"task_pipe_batch_{selected_task_id}",
                )
            with pipe_col3:
                pipeline_config["allow_multi_assign"] = st.toggle(
                    "同一条可进多个栏目",
                    value=bool(pipeline_config.get("allow_multi_assign", editorial_defaults["allow_multi_assign"])),
                    key=f"task_pipe_multi_{selected_task_id}",
                )
            with pipe_col4:
                pipeline_config["inject_publication_scope_into_global"] = st.toggle(
                    "加入刊物定位约束",
                    value=bool(
                        pipeline_config.get(
                            "inject_publication_scope_into_global",
                            editorial_defaults["inject_publication_scope_into_global"],
                        )
                    ),
                    key=f"task_pipe_scope_{selected_task_id}",
                )

            st.divider()
            with st.expander("🔬 高级 AI 设置", expanded=False):
                st.caption("这里是全局 AI 和筛选策略。普通任务配置优先改信源、栏目和频道；不确定时不要改高级项。")

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
                        "接口地址（API URL）",
                        value=merged_ai_view.get("api_url", ""),
                        key=f"task_runtime_api_url_{selected_task_id}",
                    ).strip()
                with runtime_col2:
                    runtime_api_key = st.text_input(
                        "接口密钥（API Key）",
                        value=merged_ai_view.get("api_key", ""),
                        type="password",
                        key=f"task_runtime_api_key_{selected_task_id}",
                    ).strip()
                    st.caption("运行时凭证会优先写入 config.secrets.json；如果你改用本地 runtime，后续也可以完全迁移到环境变量。")

            save_col1, save_col2 = st.columns([1, 1])
            with save_col1:
                if st.button("生成配置变更提案", key=f"save_task_all_{selected_task_id}", use_container_width=True):
                    selected_day_value = next(
                        item[1] for item in day_options if item[0] == selected_day_label
                    )
                    proposed_task_def = deepcopy(task_def)
                    proposed_task_def["name"] = new_name
                    proposed_task_def["enabled"] = new_enabled
                    proposed_task_def["pipeline"] = new_pipeline
                    proposed_task_def["channels"] = selected_channels
                    proposed_task_def["screen"] = {
                        "enabled": bool(screen_enabled),
                        "theme": screen_theme,
                        "refresh_seconds": int(screen_refresh),
                        "rotate_seconds": int(screen_rotate),
                        "image_rotate_seconds": int(screen_image_rotate),
                    }
                    if screen_title.strip():
                        proposed_task_def["screen"]["title"] = screen_title.strip()
                    proposed_sources = deepcopy(sources_editor)
                    proposed_sources["rss"] = rss_sources
                    proposed_sources["search"] = {
                        "enabled": search_enabled,
                        "provider": search_provider,
                        "queries": [q for q in search_queries if q.get("keywords", "").strip()],
                    }
                    proposed_task_def["sources"] = proposed_sources
                    proposed_task_def["sections"] = sections_editor
                    proposed_task_def["pipeline_config"] = pipeline_config
                    proposed_task_def["schedule"] = {"hour": int(new_hour), "minute": int(new_min)}
                    if selected_day_value is not None:
                        proposed_task_def["schedule"]["day_of_week"] = selected_day_value

                    proposed_config = deepcopy(config)
                    proposed_config.setdefault("ai", {})
                    proposed_config["ai"]["system_prompt"] = ai_prompt
                    proposed_config["ai"]["selection"] = {
                        "max_selected_items": int(selection_max_items),
                        "title_max_len": int(selection_title_max),
                        "summary_max_len": int(selection_summary_max),
                        "full_context_threshold_chars": int(selection_threshold),
                        "batch_size": int(selection_batch_size),
                    }

                    proposed_secrets = deepcopy(load_secrets_config())
                    proposed_secrets.setdefault("ai", {})
                    proposed_secrets["ai"]["model"] = runtime_model
                    proposed_secrets["ai"]["api_url"] = runtime_api_url
                    proposed_secrets["ai"]["api_key"] = runtime_api_key

                    try:
                        changeset = scheduler.propose_task_changeset_command(
                            selected_task_id,
                            normalize_task_definition(proposed_task_def),
                            intent="Update task configuration from Workbench",
                            rationale="User reviewed task configuration in Configure.",
                        )
                        current_version_id = selected_task_validation.get("summary", {}).get("task_version_id")
                        st.session_state[f"pending_changeset::{selected_task_id}"] = {
                            "changeset": changeset.to_dict(),
                            "proposal": build_change_proposal(changeset, current_version_id=current_version_id),
                            "config": proposed_config,
                            "secrets": proposed_secrets,
                            "task_name": proposed_task_def.get("name", selected_task_id),
                        }
                        st.info("已生成变更提案。请检查下方确认卡后再应用。")
                    except Exception as exc:
                        st.error(f"生成变更提案失败：{exc}")

            st.markdown('<div id="configure-approval"></div>', unsafe_allow_html=True)
            pending_change = st.session_state.get(f"pending_changeset::{selected_task_id}")
            if pending_change:
                proposal = pending_change.get("proposal") or {}
                st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
                st.markdown('<div class="ib-section-title">🔐 变更确认卡</div>', unsafe_allow_html=True)
                st.caption(
                    f"变更目的：{proposal.get('intent')} | 风险等级：{proposal.get('risk_level')} | "
                    f"基于版本：{proposal.get('base_version_id') or 'unknown'} | 当前版本：{proposal.get('current_version_id') or 'unknown'}"
                )
                if proposal.get("is_stale"):
                    st.error("这个变更提案基于旧配置版本，当前配置已变化。请重新生成提案。")
                else:
                    st.warning("应用后会更新任务配置，并建议重新 Dry Run。")
                with st.expander("查看变更摘要", expanded=True):
                    for line in proposal.get("human_readable_diff", []) or ["无配置差异。"]:
                        st.code(line, language="text")
                apply_col1, apply_col2 = st.columns([1, 1])
                with apply_col1:
                    if st.button(
                        "确认应用变更",
                        key=f"apply_pending_changeset::{selected_task_id}",
                        use_container_width=True,
                        disabled=bool(proposal.get("is_stale")),
                    ):
                        apply_result = scheduler.execute_tool_call(
                            "approve_and_apply_changeset",
                            {"changeset": pending_change.get("changeset") or {}},
                            approved=True,
                        )
                        if apply_result.get("ok"):
                            if pending_change.get("config") is not None:
                                config = pending_change.get("config") or config
                                save_config(config)
                            if pending_change.get("secrets") is not None:
                                save_secrets_config(pending_change.get("secrets") or {})
                            mark_task_changed(selected_task_id)
                            applied_task = normalize_task_definition(
                                (apply_result.get("output") or {}).get("tasks", {}).get(selected_task_id, {})
                            )
                            selected_task_state = load_task_state(selected_task_id, bot_dir)
                            selected_task_validation = build_task_validation(selected_task_id, applied_task)
                            st.session_state.pop(f"pending_changeset::{selected_task_id}", None)
                            st.success(
                                f"已应用任务「{pending_change.get('task_name', selected_task_id)}」的配置变更。建议重新 Dry Run。"
                            )
                            st.rerun()
                        else:
                            st.error(f"应用失败：{apply_result.get('error') or '未知错误'}")
                with apply_col2:
                    if st.button("放弃这个提案", key=f"discard_pending_changeset::{selected_task_id}", use_container_width=True):
                        st.session_state.pop(f"pending_changeset::{selected_task_id}", None)
                        st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)
            with save_col2:
                if st.button("🗑️ 删除当前任务", key=f"del_task_{selected_task_id}", use_container_width=True):
                    tasks_data = get_tasks_data()
                    if hasattr(scheduler, "delete_task_command"):
                        result = scheduler.delete_task_command(
                            selected_task_id,
                            intent="Delete task from Streamlit UI",
                            rationale="User deleted the current task in the control panel.",
                        )
                        if not result.ok:
                            st.error(result.error or "删除任务失败")
                            st.stop()
                    else:
                        tasks_data.get("tasks", {}).pop(selected_task_id, None)
                        save_tasks(tasks_data, bot_dir)
                        scheduler.reload()
                    st.session_state.pop(f"task_search_queries::{selected_task_id}", None)
                    tasks_data = get_tasks_data()
                    next_task_id = next(iter(tasks_data.get("tasks", {})), None)
                    st.session_state["selected_task_id"] = next_task_id
                    st.success("任务已删除。")
                    st.rerun()

            render_validation_result(selected_task_validation, task_state=selected_task_state)

    # ── Tab 2: Channels ────────────────────────────────────────────────────────
    with tab2:
        st.subheader("Configure / 频道")
        st.caption("管理消息发送到哪里。日常只需要确认名称、频道类型和联通性；凭证细节默认收在每个频道卡片里。")
        render_page_map(
            "本页板块",
            [
                ("📣 已有频道", "channels-existing"),
                ("🧪 联通测试", "channels-test"),
                ("➕ 添加新频道", "channels-add"),
            ],
        )

        channels_data = load_channels(bot_dir)
        if "channels" not in channels_data:
            channels_data = {"channels": {}}

        channel_ids = list(channels_data["channels"].keys())
        render_section_heading(
            "📣 已有频道",
            "每个频道以卡片折叠呈现；先看名称和类型，需要改凭证时再展开。",
            anchor="channels-existing",
        )
        for ch_id in channel_ids:
            ch = channels_data["channels"][ch_id]
            channel_type_label = CHANNEL_TYPE_LABELS.get(ch.get("type", ""), ch.get("type", "未指定类型"))
            with st.expander(f"📣 {ch.get('name', ch_id)}（{channel_type_label}）", expanded=False):
                col1, col2 = st.columns([1, 1])
                with col1:
                    new_ch_name = st.text_input("名称", value=ch.get("name", ""), key=f"ch_name_{ch_id}")
                channel_type_options = ["wecom", "feishu_app", "feishu_bot"]
                current_type = ch.get("type", "wecom")
                if current_type not in channel_type_options:
                    current_type = "wecom"
                with col2:
                    new_ch_type = st.selectbox(
                        "类型",
                        options=channel_type_options,
                        index=channel_type_options.index(current_type),
                        key=f"ch_type_{ch_id}",
                        format_func=label_for(CHANNEL_TYPE_LABELS),
                    )

                channel_payload = {
                    "type": new_ch_type,
                    "name": new_ch_name,
                }
                if new_ch_type == "wecom":
                    new_cid = st.text_input("企业 ID（Corp ID / cid）", value=ch.get("cid", ""), key=f"ch_cid_{ch_id}")
                    new_secret = st.text_input("应用密钥（Secret）", value=ch.get("secret", ""), type="password", key=f"ch_secret_{ch_id}")
                    new_agent_id = st.text_input("应用 Agent ID", value=ch.get("agent_id", ""), key=f"ch_agent_{ch_id}")
                    channel_payload.update({
                        "cid": new_cid,
                        "secret": new_secret,
                        "agent_id": new_agent_id,
                    })
                elif new_ch_type == "feishu_app":
                    st.caption("推荐方式：飞书应用鉴权后走官方消息 API；消息发送支持 richer message 卡片。")
                    new_app_id = st.text_input("飞书 App ID", value=ch.get("app_id", ""), key=f"ch_feishu_app_id_{ch_id}")
                    new_app_secret = st.text_input(
                        "飞书 App Secret",
                        value=ch.get("app_secret", ""),
                        type="password",
                        key=f"ch_feishu_app_secret_{ch_id}",
                    )
                    new_receive_id = st.text_input(
                        "接收对象 ID",
                        value=ch.get("receive_id", ""),
                        key=f"ch_feishu_receive_id_{ch_id}",
                    )
                    receive_id_type_options = ["chat_id", "open_id", "user_id", "union_id", "email"]
                    current_receive_id_type = ch.get("receive_id_type", "chat_id")
                    if current_receive_id_type not in receive_id_type_options:
                        current_receive_id_type = "chat_id"
                    new_receive_id_type = st.selectbox(
                        "接收对象类型",
                        options=receive_id_type_options,
                        index=receive_id_type_options.index(current_receive_id_type),
                        key=f"ch_feishu_receive_id_type_{ch_id}",
                        format_func=label_for(RECEIVE_ID_TYPE_LABELS),
                    )
                    message_template_options = ["interactive", "text"]
                    current_message_template = ch.get("message_template", "interactive")
                    if current_message_template not in message_template_options:
                        current_message_template = "interactive"
                    new_message_template = st.selectbox(
                        "消息模板",
                        options=message_template_options,
                        index=message_template_options.index(current_message_template),
                        key=f"ch_feishu_message_template_{ch_id}",
                        format_func=label_for(MESSAGE_TEMPLATE_LABELS),
                    )
                    channel_payload.update({
                        "app_id": new_app_id,
                        "app_secret": new_app_secret,
                        "receive_id": new_receive_id,
                        "receive_id_type": new_receive_id_type,
                        "message_template": new_message_template,
                    })
                else:
                    new_webhook_url = st.text_input(
                        "Webhook 地址",
                        value=ch.get("webhook_url", ""),
                        key=f"ch_webhook_{ch_id}",
                    )
                    new_mention_all = st.toggle(
                        "测试和发送时 @所有人",
                        value=bool(ch.get("mention_all", False)),
                        key=f"ch_mention_all_{ch_id}",
                    )
                    channel_payload.update({
                        "webhook_url": new_webhook_url,
                        "mention_all": new_mention_all,
                    })

                render_channel_validation(ch_id, channel_payload)

                col_btn1, col_btn2, col_btn3 = st.columns(3)
                with col_btn1:
                    if st.button("💾 保存", key=f"ch_save_{ch_id}"):
                        channels_data["channels"][ch_id] = channel_payload
                        save_channels(channels_data, bot_dir)
                        init_channels(channels_data)
                        mark_tasks_changed(list(get_tasks_data().get("tasks", {}).keys()))
                        st.success("已保存！")
                        st.rerun()
                with col_btn2:
                    if st.button("🧪 测试联通性", key=f"ch_test_{ch_id}"):
                        try:
                            ok = test_channel_config(ch_id, channel_payload)
                            if ok:
                                st.success("✅ 频道连通性测试成功！")
                            else:
                                st.error("❌ 频道连通性测试失败，请检查配置。")
                        except Exception as e:
                            st.error(f"错误: {e}")
                with col_btn3:
                    if st.button("🗑️ 删除", key=f"ch_del_{ch_id}"):
                        referenced_tasks = get_channel_reference_tasks(ch_id)
                        if referenced_tasks:
                            st.error(
                                "该频道仍被以下任务引用，不能直接删除："
                                + "、".join(referenced_tasks)
                            )
                        else:
                            channels_data["channels"].pop(ch_id, None)
                            save_channels(channels_data, bot_dir)
                            init_channels(channels_data)
                            mark_tasks_changed(list(get_tasks_data().get("tasks", {}).keys()))
                            st.success("已删除！")
                            st.rerun()

        render_section_heading(
            "🧪 联通测试",
            "展开任一频道卡片后，可使用卡片内的测试按钮检查凭证和通道是否可用。",
            anchor="channels-test",
        )
        if not channel_ids:
            st.info("暂无频道。先在下方添加频道后再测试联通性。")

        st.divider()
        render_section_heading("➕ 添加新频道", "新增后再展开频道卡片补齐凭证并测试联通性。", anchor="channels-add")
        col_n1, col_n2, col_n3 = st.columns([2, 1, 1])
        with col_n1:
            new_ch_id = st.text_input("频道 ID（唯一标识）", placeholder="wecom_test")
        with col_n2:
            new_ch_name_input = st.text_input("名称", placeholder="测试频道")
        with col_n3:
            new_ch_type_input = st.selectbox(
                "类型",
                options=["wecom", "feishu_app", "feishu_bot"],
                index=0,
                format_func=label_for(CHANNEL_TYPE_LABELS),
            )

        if st.button("添加频道", key="add_channel_btn"):
            if new_ch_id and not is_safe_id(new_ch_id):
                st.error("频道 ID 只能使用英文字母、数字、下划线和连字符，长度 1-64。")
            elif new_ch_id and new_ch_id not in channels_data["channels"]:
                channels_data["channels"][new_ch_id] = {
                    "type": new_ch_type_input,
                    "name": new_ch_name_input or new_ch_id,
                }
                if new_ch_type_input == "wecom":
                    channels_data["channels"][new_ch_id].update({
                        "cid": "",
                        "secret": "",
                        "agent_id": "",
                    })
                elif new_ch_type_input == "feishu_app":
                    channels_data["channels"][new_ch_id].update({
                        "app_id": "",
                        "app_secret": "",
                        "receive_id": "",
                        "receive_id_type": "chat_id",
                        "message_template": "interactive",
                    })
                else:
                    channels_data["channels"][new_ch_id].update({
                        "webhook_url": "",
                        "mention_all": False,
                    })
                save_channels(channels_data, bot_dir)
                init_channels(channels_data)
                mark_tasks_changed(list(get_tasks_data().get("tasks", {}).keys()))
                st.success(f"频道「{new_ch_id}」已添加！")
                st.rerun()
            elif new_ch_id in channels_data["channels"]:
                st.error("频道 ID 已存在。")

    with tab3:
        st.subheader("Investigate / 排查")
        st.caption("先看证据链判断卡在哪里：信源、候选、AI 筛选、输出或发送。需要深挖时再展开下面的调试工具。")
        render_page_map(
            "本页板块",
            [
                ("🧭 证据链", "investigate-chain"),
                ("📌 最近验证", "investigate-validation"),
                ("🎯 聚焦板块", "investigate-focus"),
                ("🧰 Prompt 调试", "investigate-prompt-debug"),
                ("📜 相关日志", "investigate-logs"),
            ],
        )

        evidence = workspace_state.get("selected_run_evidence") or {}
        source_summary = workspace_state.get("selected_source_health") or {}
        human_diagnosis = workspace_state.get("human_diagnosis") or {}
        st.markdown('<div id="investigate-chain" class="ib-panel">', unsafe_allow_html=True)
        st.markdown('<div class="ib-section-title">🧭 证据链：从信源到发送</div>', unsafe_allow_html=True)
        st.caption(human_diagnosis.get("message") or "还没有可用诊断。")
        chain_col1, chain_col2, chain_col3, chain_col4 = st.columns(4)
        with chain_col1:
            st.metric(
                "1. 信源",
                f"{source_summary.get('ok_count', 0)}/{source_summary.get('source_count', 0)} OK",
                delta=f"{source_summary.get('error_count', 0)} error / {source_summary.get('stale_count', 0)} stale",
                delta_color="inverse",
            )
        stage_counts = evidence.get("stage_counts") or {}
        with chain_col2:
            fetch_count = (stage_counts.get("fetch") or {}).get("output", 0)
            screen_count = (stage_counts.get("screen") or stage_counts.get("screen_global") or {}).get("output", 0)
            st.metric("2. 候选", f"{fetch_count} -> {screen_count}")
        with chain_col3:
            render_count = (stage_counts.get("render") or {}).get("output", 0)
            st.metric("3. 输出", "有预览" if evidence.get("has_output") else "无输出", delta=f"render {render_count}")
        with chain_col4:
            channel_results = evidence.get("channel_results") or []
            sent_count = sum(1 for item in channel_results if isinstance(item, dict) and item.get("ok"))
            st.metric("4. 发送", f"{sent_count}/{len(channel_results)} sent" if channel_results else "未发送")

        if source_summary.get("top_failing_sources"):
            with st.expander("⚠️ 异常信源", expanded=False):
                for item in source_summary.get("top_failing_sources", []):
                    diagnosis = item.get("diagnosis") or describe_feed_issue(item)
                    st.markdown(f"**{item.get('name') or item.get('url')}**")
                    st.caption(f"状态：{item.get('status') or 'unknown'} | 类型：{item.get('error_type') or '无'}")
                    st.warning(f"{diagnosis.get('summary', '暂无法判断问题。')} 建议：{diagnosis.get('action', '先手动检查该信源。')}")
        if stage_counts:
            with st.expander("🧪 开发细节：运行阶段计数", expanded=False):
                st.json(stage_counts, expanded=False)
        if evidence.get("output_preview"):
            with st.expander("📝 输出预览", expanded=True):
                st.markdown(evidence["output_preview"])
        else:
            st.info("当前没有输出预览。请先 Dry Run，或检查候选/筛选链路。")
        st.markdown("</div>", unsafe_allow_html=True)

        health_snapshot = load_task_health(selected_task_id, bot_dir) if selected_task_id else None
        run_summary = parse_recent_run_summary(bot_log_path)
        task_prompt_history = filter_prompt_history_for_task(load_prompt_debug_history(bot_dir), selected_task_id)
        focused_category = get_verification_focus(selected_task_id)

        st.markdown('<div id="investigate-validation" class="ib-panel">', unsafe_allow_html=True)
        st.markdown('<div class="ib-section-title">📌 最近验证记录</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="ib-section-copy">这里补充最近运行、最近成功发送、健康快照和 prompt 调试记录。通常先看上方证据链。</div>',
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

        render_inline_dry_run_panel(
            selected_task_id=selected_task_id,
            selected_task=selected_task,
            scheduler=scheduler,
            summarize_task_debug_result=summarize_task_debug_result,
        )

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

            st.markdown('<div id="investigate-focus" class="ib-panel">', unsafe_allow_html=True)
            st.markdown('<div class="ib-section-title">🎯 聚焦板块下一步</div>', unsafe_allow_html=True)
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

        st.markdown('<div id="investigate-prompt-debug"></div>', unsafe_allow_html=True)
        with st.expander("🧰 高级 Prompt 调试（可选）", expanded=False):
            st.caption(
                "这里只测试单个板块 prompt，不代表完整推送结果。日常判断请优先看上方 Dry Run 的四阶段结果。"
            )
            if not selected_task_categories:
                st.info("当前任务还没有板块，先去“任务管理”添加板块和 RSS 源。")
            else:
                st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
                st.markdown('<div class="ib-section-title">🧪 单板块 Prompt 调试</div>', unsafe_allow_html=True)
                st.markdown(
                    '<div class="ib-section-copy">用于局部验证某个板块的 prompt。它不会经过完整的全局初筛和板块分配链路。</div>',
                    unsafe_allow_html=True,
                )
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

                debug_action1, debug_action2, debug_action3 = st.columns(3)
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
                    if st.button("💾 写回草稿", key=f"inline_writeback::{debug_category}", use_container_width=True):
                        tasks_data = get_tasks_data()
                        task_def = normalize_task_definition(deepcopy(tasks_data.get("tasks", {}).get(selected_task_id, {})))
                        task_def.setdefault("sections", {}).setdefault(debug_category, {}).update(
                            {**task_def.get("sections", {}).get(debug_category, {}), "prompt": draft_prompt}
                        )
                        if save_task_definition(
                            selected_task_id,
                            task_def,
                            intent="Update section prompt from Workbench",
                            rationale=f"User requested writing back draft prompt for {debug_category}.",
                        ):
                            st.info(f"已生成写回 [{debug_category}] Prompt 的变更提案，请在确认卡中应用。")

                if debug_candidates:
                    single_result = st.session_state.get("prompt_debug_result", {})
                    selected_count = 0
                    if single_result.get("category") == debug_category:
                        selected_count = len((single_result.get("result") or {}).get("selected_items", []))
                    render_kpi_strip(
                        candidate_count=len(debug_candidates),
                        selected_count=selected_count,
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
                    st.info("当前还没有候选内容。先抓取一批候选，再试跑草稿。")

                single_result = st.session_state.get("prompt_debug_result", {})
                if single_result.get("category") == debug_category and single_result.get("result"):
                    render_result_panel(title="草稿试跑结果", result=single_result["result"])

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
        active_task_name = selected_task.get("name", selected_task_id) if selected_task_id else "未选择任务"

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
                st.markdown('<div class="ib-eyebrow">未推送诊断</div>', unsafe_allow_html=True)
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
                        diagnosis = describe_feed_issue(feed)
                        st.error(f"{diagnosis['summary']} 建议：{diagnosis['action']}")
                    elif feed.get("status") == "stale":
                        diagnosis = describe_feed_issue(feed)
                        st.warning(f"{diagnosis['summary']} 建议：{diagnosis['action']}")
                    else:
                        elapsed = feed.get("elapsed_s")
                        if elapsed is not None:
                            st.caption(f"响应耗时：{elapsed}s")
                st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div id="investigate-logs" class="ib-panel">', unsafe_allow_html=True)
        st.markdown('<div class="ib-section-title">📜 最近相关日志</div>', unsafe_allow_html=True)
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
        st.subheader("Investigate / 深度日志")
        st.caption("日志已开启企业级轮转模式（自动保留 30 天，每日切割）。默认优先展示当前任务相关日志，便于快速排查。")
        render_page_map(
            "本页板块",
            [
                ("🔄 刷新日志", "deep-logs-refresh"),
                ("📥 下载完整日志", "deep-logs-download"),
                ("📜 当前任务相关日志", "deep-logs-task"),
                ("🧾 最近全量日志", "deep-logs-all"),
            ],
        )
        st.markdown(
            f'<div class="ib-chip-row"><span class="ib-chip ib-chip-neutral">当前任务: {active_task_name}</span>'
            f'<span class="ib-chip ib-chip-neutral">任务 ID: {selected_task_id or "未选择"}</span></div>',
            unsafe_allow_html=True,
        )

        col_1, col_2, col_3 = st.columns([6, 1.5, 1.5])
        with col_2:
            st.markdown('<div id="deep-logs-refresh"></div>', unsafe_allow_html=True)
            if st.button("🔄 刷新日志追踪"):
                st.rerun()
        with col_3:
            st.markdown('<div id="deep-logs-download"></div>', unsafe_allow_html=True)
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
                    st.markdown('<div id="deep-logs-task"></div>', unsafe_allow_html=True)
                    st.markdown("**当前任务相关日志**")
                    st.code(last_filtered_lines or "当前日志中还没有匹配该任务 ID 的记录。", language="bash")
                    st.markdown('<div id="deep-logs-all"></div>', unsafe_allow_html=True)
                    st.markdown("**最近全量日志**")
                st.code(last_lines, language="bash")
            except Exception as e:
                st.error(f"读取日志出错: {e}")
        else:
            st.info("暂无深度日志。请点击侧边栏【立即手动运行】生成第一份报告。")

    with tab5:
        st.subheader("Configure / 输出版式")
        st.caption("这里只管最终推送文案的标题、空状态和底部链接，不影响信源、AI 筛选或频道。")
        render_page_map(
            "本页板块",
            [
                ("📰 早报标题", "output-title"),
                ("📭 无更新提示", "output-empty"),
                ("🔗 底部链接", "output-footer"),
            ],
        )
        settings = config["settings"]

        render_section_heading("📰 早报标题", anchor="output-title")
        settings["report_title"] = st.text_input(
            "早报大标题 ({date} 会自动替换为当天日期)",
            value=settings.get("report_title", "📅 营销情报早报 | {date}"),
        )
        st.markdown('<div id="output-empty"></div>', unsafe_allow_html=True)
        settings["empty_message"] = st.text_input(
            "无更新时的提示语", value=settings.get("empty_message", "📭 今日全网无重要更新。")
        )

        st.divider()
        render_section_heading("🔗 底部链接", anchor="output-footer")
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

if __name__ == "__main__":
    main()
