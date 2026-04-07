import json
import logging
import os
import subprocess
import sys
from datetime import datetime

import streamlit as st
from crontab import CronTab

from insightbot.config import load_runtime_config
from insightbot.feed_health import CACHE_TTL_SECONDS, get_feed_health_snapshot, load_health_cache
from insightbot.paths import (
    bot_log_file_path,
    config_content_file_path,
    config_file_path,
    config_secrets_file_path,
    cron_log_file_path,
    default_bot_dir,
    feed_health_cache_file_path,
)
from insightbot.prompt_debug_history import (
    append_prompt_debug_history,
    load_prompt_debug_history,
    make_compare_record,
    make_draft_run_record,
)
from insightbot.discovery.url_resolver import UrlResolver
from insightbot.run_diagnosis import build_no_push_diagnosis, parse_recent_run_summary, summarize_recent_run
from insightbot.smart_brief_runner import DEBUG_SAMPLE_NEWS, fetch_recent_candidates, run_prompt_debug

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

    def render_diagnosis_card(card: dict, *, prompt_categories: list[str], key_prefix: str) -> None:
        st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
        st.markdown(f'<div class="ib-section-title">{card["title"]}</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="ib-section-copy">{card["summary"]}<br/>下一步：{card["next_step"]}</div>',
            unsafe_allow_html=True,
        )
        kind = card.get("kind")
        if kind == "prompt_block":
            blocked = [item.get("category") for item in card.get("details", []) if item.get("category")]
            if blocked:
                default_category = blocked[0]
                if st.button(
                    f"🎯 预设到 Prompt Debug：{default_category}",
                    key=f"{key_prefix}_diag_prompt_{default_category}",
                ):
                    st.session_state["prompt_debug_category"] = default_category
                    if default_category in prompt_categories:
                        draft_key = f"draft_prompt::{default_category}"
                        if draft_key not in st.session_state:
                            st.session_state[draft_key] = config.get("feeds", {}).get(default_category, {}).get("prompt", "")
                    st.success("已预设 Prompt Debug 板块，请切到“🧠 AI 提示词调优”继续。")
        elif kind == "source_error":
            st.caption("建议先在当前页的 RSS 健康度列表里查看这些异常源。")
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

    def add_rss_feed_to_config(feed_url: str, category: str, feed_name: str = "") -> bool:
        """添加单个 RSS 源到 config.json"""
        try:
            cfg = load_config()
            if "feeds" not in cfg:
                cfg["feeds"] = {}
            if category not in cfg["feeds"]:
                cfg["feeds"][category] = {"rss": [], "keywords": [], "prompt": ""}
            
            # 去重检查
            existing_urls = [item.split(" # ")[0].strip() if isinstance(item, str) else item.get("feed_url", "") 
                           for item in cfg["feeds"][category].get("rss", [])]
            if feed_url in existing_urls:
                return False  # 已存在
            
            # 格式化: "url # name" 或纯 url
            entry = f"{feed_url} # {feed_name}" if feed_name else feed_url
            cfg["feeds"][category]["rss"].append(entry)
            save_config(cfg)
            return True
        except Exception as e:
            st.error(f"保存失败: {e}")
            return False

    config = load_config()
    runtime_config = load_runtime_view()
    overview_health_snapshot = load_health_cache(bot_dir)
    overview_run_summary = parse_recent_run_summary(bot_log_path)
    overview_run_metrics = summarize_recent_run(overview_run_summary)
    overview_diagnosis_cards = build_no_push_diagnosis(
        health_snapshot=overview_health_snapshot,
        run_summary=overview_run_summary,
        configured_categories=list(config.get("feeds", {}).keys()),
    )
    overview_prompt_history = load_prompt_debug_history(bot_dir)

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
        if st.button("▶️ 立即手动运行", type="primary", use_container_width=True):
            with st.spinner("AI 正在全网检索并撰写简报..."):
                if smart_brief_mode == "module":
                    subprocess.run([sys.executable, "-m", "insightbot.cli"])
                else:
                    subprocess.run([sys.executable, smart_brief_path])
                st.success("运行指令已发送，请查看企业微信或日志。")

        st.divider()
        st.header("⏳ 定时推送设置")
        server_time = subprocess.run(["date", "+%H:%M"], capture_output=True, text=True).stdout.strip()
        st.caption(f"服务器当前时间: {server_time}")

        current_hour, current_minute = 9, 0
        try:
            cron = CronTab(user="root")
            for job in cron:
                if job.comment == "marketing_task":
                    parts = str(job).split()
                    current_minute, current_hour = int(parts[0]), int(parts[1])
                    break
        except Exception:
            pass

        from datetime import time

        new_time = st.time_input("每天自动推送时间", value=time(current_hour, current_minute))

        if st.button("保存定时设置", use_container_width=True):
            try:
                cron = CronTab(user="root")
                cron.remove_all(comment="marketing_task")
                python_bin = os.getenv("PYTHON_BIN", sys.executable or "/usr/bin/python3")
                if smart_brief_mode == "module":
                    cmd = f'{python_bin} -m insightbot.cli >> "{cron_log_path}" 2>&1'
                else:
                    cmd = f'{python_bin} "{smart_brief_path}" >> "{cron_log_path}" 2>&1'
                job = cron.new(command=cmd, comment="marketing_task")
                job.setall(f"{new_time.minute} {new_time.hour} * * *")
                cron.write()
                st.success("定时已更新！")
            except Exception:
                st.error("保存失败，请检查权限。")

    tab0, tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["🏠 概览", "📊 板块与信源管理", "⚙️ 推送版式定制", "🧠 AI 提示词调优", "🩺 RSS 健康度", "📝 运行日志", "🔍 信源发现"])

    with tab0:
        st.subheader("运营概览")
        st.caption("这里不是实时计算中心，而是最近状态总览。优先看最近一次任务、异常摘要和最近调试动作。")

        health_counts = (overview_health_snapshot or {}).get("counts", {})
        st.markdown(
            f"""
            <div class="ib-kpi-grid">
              <div class="ib-kpi-card">
                <div class="ib-kpi-label">今日板块数</div>
                <div class="ib-kpi-value">{len(config.get('feeds', {}))}</div>
              </div>
              <div class="ib-kpi-card">
                <div class="ib-kpi-label">异常 RSS 源</div>
                <div class="ib-kpi-value">{health_counts.get('error', 0)}</div>
              </div>
              <div class="ib-kpi-card">
                <div class="ib-kpi-label">最近运行结果</div>
                <div class="ib-kpi-value" style="font-size:1.05rem;">{overview_run_metrics.get('result_label', '未知')}</div>
              </div>
              <div class="ib-kpi-card">
                <div class="ib-kpi-label">今日候选总条数</div>
                <div class="ib-kpi-value">{overview_run_metrics.get('candidate_total', 0)}</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        top_col1, top_col2 = st.columns([1.35, 1.0])
        with top_col1:
            st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
            st.markdown('<div class="ib-section-title">最近一次任务</div>', unsafe_allow_html=True)
            task_started_at = overview_run_metrics.get("task_started_at")
            started_copy = format_timestamp(task_started_at) if task_started_at else "暂无记录"
            st.markdown(
                f"""
                <div class="ib-section-copy">
                  最近开始时间：{started_copy}<br/>
                  已推送板块：{overview_run_metrics.get('pushed_count', 0)}<br/>
                  Prompt 全拦截：{overview_run_metrics.get('blocked_count', 0)}<br/>
                  无候选板块：{overview_run_metrics.get('no_candidate_count', 0)}<br/>
                  AI 异常板块：{overview_run_metrics.get('ai_error_count', 0)}
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown("</div>", unsafe_allow_html=True)

        with top_col2:
            st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
            st.markdown('<div class="ib-section-title">最近调试动态</div>', unsafe_allow_html=True)
            st.markdown(
                '<div class="ib-section-copy">来自 Prompt Debug 的最近记录，帮助你判断最近都在调哪些板块。</div>',
                unsafe_allow_html=True,
            )
            if overview_prompt_history:
                for item in overview_prompt_history[:3]:
                    mode_label = "草稿试跑" if item.get("mode") == "draft_run" else "当前 vs 草稿"
                    st.markdown(
                        f"- {item.get('created_at', '')} | {item.get('category', '未命名板块')} | {mode_label} | 草稿状态：{item.get('draft_status', '未知')}"
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
                    prompt_categories=list(config.get("feeds", {}).keys()),
                    key_prefix="overview",
                )
        else:
            st.success("当前没有明显异常摘要，系统状态看起来比较稳定。")
        st.markdown("</div>", unsafe_allow_html=True)

    with tab1:
        st.subheader("内容板块控制")
        st.caption("填入定向 RSS 源。AI 将根据你设定的专属筛选标准进行高标准的过滤清洗。")

        feeds = config.get("feeds", {})
        categories_to_delete = []

        for category, feed_data in feeds.items():
            with st.expander(f"📂 {category}", expanded=False):
                rss_val = "\n".join(feed_data.get("rss", []))
                new_rss = st.text_area(
                    "🔗 定向 RSS 源 (主力抓取渠道，每行一个)",
                    value=rss_val,
                    height=150,
                    key=f"rss_{category}",
                )

                new_kw = "\n".join(feed_data.get("keywords", []))

                prompt_val = feed_data.get("prompt", "")
                new_prompt = st.text_area(
                    "🧠 本板块专属筛选标准 (必填：决定 AI 的品味)",
                    value=prompt_val,
                    height=80,
                    key=f"prompt_{category}",
                )

                feeds[category] = {
                    "rss": [x.strip() for x in new_rss.split("\n") if x.strip()],
                    "keywords": [x.strip() for x in new_kw.split("\n") if x.strip()],
                    "prompt": new_prompt.strip(),
                }

                if st.button(f"🗑️ 删除 [{category}] 板块", key=f"del_{category}"):
                    categories_to_delete.append(category)

        for cat in categories_to_delete:
            del feeds[cat]
            config["feeds"] = feeds
            save_config(config)
            st.rerun()

        st.divider()
        new_cat_name = st.text_input("✨ 新增板块名称 (如：🚗 汽车行业动态)")
        if st.button("添加板块"):
            if new_cat_name and new_cat_name not in feeds:
                feeds[new_cat_name] = {"rss": [], "keywords": [], "prompt": ""}
                config["feeds"] = feeds
                save_config(config)
                st.rerun()

        if st.button("💾 保存所有信源更改", type="primary"):
            config["feeds"] = feeds
            save_config(config)
            st.toast("信源配置已保存！")

    with tab2:
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
            st.toast("设置已生效！")

    with tab3:
        ai_conf = config.get("ai", {})
        runtime_ai = runtime_config.get("ai", {})
        feeds = config.get("feeds", {})
        categories = list(feeds.keys())
        if "prompt_debug_category" not in st.session_state and categories:
            st.session_state["prompt_debug_category"] = categories[0]

        st.markdown(
            """
            <div class="ib-hero">
              <div class="ib-eyebrow">Prompt Debug Console</div>
              <div class="ib-title">让管理员先试跑，再决定是否落盘</div>
              <div class="ib-subtitle">
                当前工作流只做一件事：先抓真实候选内容，再用草稿 Prompt 试跑，最后才选择是否把草稿写回内容配置。
                运行时 AI 连接配置保持只读，避免把调优动作和生产连接参数混在一起。
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        top_col1, top_col2 = st.columns([1.45, 1.0])
        with top_col1:
            st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
            st.markdown('<div class="ib-section-title">全局 System Prompt</div>', unsafe_allow_html=True)
            st.markdown(
                '<div class="ib-section-copy">这是所有板块共享的全局系统规则。这里的保存会写入内容配置；不会触碰 AI 的运行时连接信息。</div>',
                unsafe_allow_html=True,
            )
            st.text_area(
                "System Prompt (系统提示词)",
                value=ai_conf.get("system_prompt", ""),
                height=220,
                key="sys_prompt",
                label_visibility="collapsed",
            )
            if st.button("💾 保存 System Prompt", use_container_width=True):
                config["ai"]["system_prompt"] = st.session_state.sys_prompt
                save_config(config)
                st.toast("System Prompt 更新成功。")
            st.markdown("</div>", unsafe_allow_html=True)

        with top_col2:
            env_ai_override_names = ["AI_API_KEY", "AI_API_URL", "AI_MODEL"]
            env_ai_overrides = [name for name in env_ai_override_names if os.getenv(name)]
            secrets_config = load_secrets_config()
            secrets_ai = secrets_config.setdefault("ai", {})
            st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
            st.markdown('<div class="ib-section-title">运行时 AI 连接</div>', unsafe_allow_html=True)
            if env_ai_overrides:
                st.markdown(
                    '<div class="ib-section-copy">当前检测到环境变量覆盖，控制台里的保存不会立刻生效。请先移除环境变量覆盖，或直接改服务器环境。</div>',
                    unsafe_allow_html=True,
                )
                st.warning(f"当前环境变量覆盖项：{', '.join(env_ai_overrides)}")
                st.text_input("AI Model", value=runtime_ai.get("model", ""), disabled=True)
                st.text_input("API URL", value=runtime_ai.get("api_url", ""), disabled=True)
                masked_api_key = runtime_ai.get("api_key", "")
                if masked_api_key:
                    st.caption(f"API Key：{masked_api_key[:6]}...{masked_api_key[-4:]}")
                else:
                    st.warning("当前未检测到 AI API Key。请在 config.secrets.json 或环境变量中配置。")
            else:
                st.markdown(
                    '<div class="ib-section-copy">这些值会写入 config.secrets.json，保存后会立即用于当前控制台调试。</div>',
                    unsafe_allow_html=True,
                )
                st.text_input(
                    "AI Model",
                    value=secrets_ai.get("model", runtime_ai.get("model", "")),
                    key="runtime_ai_model",
                )
                st.text_input(
                    "API URL",
                    value=secrets_ai.get("api_url", runtime_ai.get("api_url", "")),
                    key="runtime_ai_url",
                )
                st.text_input(
                    "API Key",
                    value=secrets_ai.get("api_key", runtime_ai.get("api_key", "")),
                    type="password",
                    key="runtime_ai_key",
                )
                if st.button("💾 保存 AI 连接", use_container_width=True):
                    secrets_ai["model"] = st.session_state["runtime_ai_model"].strip()
                    secrets_ai["api_url"] = st.session_state["runtime_ai_url"].strip()
                    secrets_ai["api_key"] = st.session_state["runtime_ai_key"].strip()
                    save_secrets_config(secrets_config)
                    st.toast("AI 连接配置已写入 config.secrets.json")
                    st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        st.divider()
        if not categories:
            st.info("当前还没有板块。请先在“板块与信源管理”里创建板块。")
        else:
            selected_category = st.selectbox(
                "调试板块",
                options=categories,
                index=categories.index(st.session_state["prompt_debug_category"])
                if st.session_state["prompt_debug_category"] in categories else 0,
                key="prompt_debug_category",
            )
            current_prompt = feeds.get(selected_category, {}).get("prompt", "")
            draft_key = f"draft_prompt::{selected_category}"
            if draft_key not in st.session_state:
                st.session_state[draft_key] = current_prompt
            prompt_changed = st.session_state[draft_key].strip() != current_prompt.strip()

            prompt_col1, prompt_col2 = st.columns(2)
            with prompt_col1:
                st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
                st.markdown('<div class="ib-section-title">当前已保存 Prompt</div>', unsafe_allow_html=True)
                st.markdown(
                    '<div class="ib-section-copy">这里显示当前内容配置里真正会被生产任务读取的板块 Prompt。</div>',
                    unsafe_allow_html=True,
                )
                st.text_area(
                    "当前已保存板块 Prompt",
                    value=current_prompt,
                    height=170,
                    disabled=True,
                    key=f"saved_prompt_{selected_category}",
                    label_visibility="collapsed",
                )
                st.markdown("</div>", unsafe_allow_html=True)

            with prompt_col2:
                st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
                st.markdown('<div class="ib-section-title">草稿 Prompt</div>', unsafe_allow_html=True)
                st.markdown(
                    '<div class="ib-section-copy">这里的编辑只存在于当前会话，直到你手动“写回编辑区”为止。</div>',
                    unsafe_allow_html=True,
                )
                st.text_area(
                    "草稿 Prompt（仅用于调试）",
                    key=draft_key,
                    height=170,
                    label_visibility="collapsed",
                )
                if prompt_changed:
                    st.markdown(
                        '<div class="ib-chip-row"><span class="ib-chip ib-chip-warning">草稿已偏离当前配置</span></div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        '<div class="ib-chip-row"><span class="ib-chip ib-chip-neutral">草稿与当前配置一致</span></div>',
                        unsafe_allow_html=True,
                    )
                st.markdown("</div>", unsafe_allow_html=True)

            action_col1, action_col2, action_col3, action_col4 = st.columns(4)
            with action_col1:
                if st.button("📥 抓取最新候选", use_container_width=True):
                    ui_logger = build_ui_logger()
                    candidates = fetch_recent_candidates(feed_data=feeds.get(selected_category, {}), logger=ui_logger)
                    using_fallback = False
                    if not candidates:
                        candidates = list(DEBUG_SAMPLE_NEWS)
                        using_fallback = True
                    st.session_state["prompt_debug_candidates"] = candidates
                    st.session_state["prompt_debug_meta"] = {
                        "category": selected_category,
                        "using_fallback": using_fallback,
                    }
                    st.session_state.pop("prompt_debug_result", None)
                    st.session_state.pop("prompt_debug_compare", None)
                    if using_fallback:
                        st.warning("实时 RSS 未抓到近 24 小时候选，已自动切换为内置样例数据。")
                    else:
                        st.success(f"已抓取 {len(candidates)} 条候选内容。")

            with action_col2:
                if st.button("🧪 运行草稿 Prompt", use_container_width=True):
                    candidates = st.session_state.get("prompt_debug_candidates", [])
                    meta = st.session_state.get("prompt_debug_meta", {})
                    if not candidates or meta.get("category") != selected_category:
                        st.warning("请先为当前板块抓取候选内容。")
                    else:
                        ui_logger = build_ui_logger()
                        debug_result = run_prompt_debug(
                            config=runtime_config,
                            category_name=selected_category,
                            news_list=candidates,
                            category_prompt=st.session_state[draft_key],
                            logger=ui_logger,
                        )
                        append_prompt_debug_history(
                            bot_dir,
                            make_draft_run_record(
                                category=selected_category,
                                candidate_count=len(candidates),
                                result=debug_result,
                                using_fallback_candidates=bool(meta.get("using_fallback")),
                                draft_prompt=st.session_state[draft_key],
                            ),
                        )
                        st.session_state["prompt_debug_result"] = debug_result
                        st.session_state["prompt_debug_result_category"] = selected_category
                        st.session_state.pop("prompt_debug_compare", None)

            with action_col3:
                if st.button("⚖️ 对比当前 vs 草稿", use_container_width=True):
                    candidates = st.session_state.get("prompt_debug_candidates", [])
                    meta = st.session_state.get("prompt_debug_meta", {})
                    if not candidates or meta.get("category") != selected_category:
                        st.warning("请先为当前板块抓取候选内容。")
                    else:
                        ui_logger = build_ui_logger()
                        current_result = run_prompt_debug(
                            config=runtime_config,
                            category_name=selected_category,
                            news_list=candidates,
                            category_prompt=current_prompt,
                            logger=ui_logger,
                        )
                        draft_result = run_prompt_debug(
                            config=runtime_config,
                            category_name=selected_category,
                            news_list=candidates,
                            category_prompt=st.session_state[draft_key],
                            logger=ui_logger,
                        )
                        st.session_state["prompt_debug_compare"] = {
                            "category": selected_category,
                            "current": current_result,
                            "draft": draft_result,
                        }
                        append_prompt_debug_history(
                            bot_dir,
                            make_compare_record(
                                category=selected_category,
                                candidate_count=len(candidates),
                                saved_result=current_result,
                                draft_result=draft_result,
                                using_fallback_candidates=bool(meta.get("using_fallback")),
                                draft_prompt=st.session_state[draft_key],
                            ),
                        )
                        st.session_state.pop("prompt_debug_result", None)

            with action_col4:
                if st.button("↩️ 草稿覆盖到编辑区", use_container_width=True):
                    feeds[selected_category]["prompt"] = st.session_state[draft_key].strip()
                    config["feeds"] = feeds
                    save_config(config)
                    st.toast(f"已将草稿 Prompt 写回 [{selected_category}]。")
                    st.rerun()

            candidates = st.session_state.get("prompt_debug_candidates", [])
            meta = st.session_state.get("prompt_debug_meta", {})
            debug_result = st.session_state.get("prompt_debug_result")
            compare_result = st.session_state.get("prompt_debug_compare")
            prompt_debug_history = load_prompt_debug_history(bot_dir)
            result_matches_category = debug_result and st.session_state.get("prompt_debug_result_category") == selected_category
            compare_matches_category = compare_result and compare_result.get("category") == selected_category
            if candidates and meta.get("category") == selected_category:
                st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
                st.markdown('<div class="ib-section-title">候选池</div>', unsafe_allow_html=True)
                st.markdown(
                    '<div class="ib-section-copy">这里是本次调试会送进 AI 的原始候选内容。先确认候选池质量，再判断 Prompt 是否合理。</div>',
                    unsafe_allow_html=True,
                )
                if compare_matches_category:
                    selected_count = len(compare_result["draft"].get("selected_items", []))
                else:
                    selected_count = len(debug_result.get("selected_items", [])) if result_matches_category else 0
                render_kpi_strip(
                    candidate_count=len(candidates),
                    selected_count=selected_count,
                    using_fallback=bool(meta.get("using_fallback")),
                    prompt_changed=prompt_changed,
                )
                candidate_preview = candidates[:12]
                st.markdown("**候选预览**")
                st.markdown('<ol class="ib-list">', unsafe_allow_html=True)
                for item in candidate_preview:
                    title = item.get("title", "").strip()
                    link = item.get("link", "").strip()
                    st.markdown(f'<li><a href="{link}">{title}</a></li>', unsafe_allow_html=True)
                st.markdown("</ol>", unsafe_allow_html=True)
                if len(candidates) > len(candidate_preview):
                    st.caption(f"还有 {len(candidates) - len(candidate_preview)} 条候选未展开显示。")
                st.markdown("</div>", unsafe_allow_html=True)

            if compare_matches_category:
                current_result = compare_result["current"]
                draft_result = compare_result["draft"]
                current_selected = len(current_result.get("selected_items", []))
                draft_selected = len(draft_result.get("selected_items", []))
                delta = draft_selected - current_selected

                st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
                st.markdown('<div class="ib-section-title">当前版 vs 草稿版</div>', unsafe_allow_html=True)
                st.markdown(
                    '<div class="ib-section-copy">两边使用同一批候选内容，方便直接比较草稿 Prompt 是否真的优于当前版本。</div>',
                    unsafe_allow_html=True,
                )
                delta_label = f"草稿多命中 {delta} 条" if delta > 0 else (f"草稿少命中 {abs(delta)} 条" if delta < 0 else "命中数量一致")
                delta_class = "ib-chip-success" if delta > 0 else ("ib-chip-warning" if delta < 0 else "ib-chip-neutral")
                st.markdown(
                    f'<div class="ib-chip-row"><span class="ib-chip {delta_class}">{delta_label}</span></div>',
                    unsafe_allow_html=True,
                )
                compare_col1, compare_col2 = st.columns(2)
                with compare_col1:
                    render_result_panel(title="当前已保存 Prompt", result=current_result)
                with compare_col2:
                    render_result_panel(title="草稿 Prompt", result=draft_result)
                st.markdown("</div>", unsafe_allow_html=True)
            elif result_matches_category:
                status = debug_result.get("status", "unknown")
                st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
                st.markdown('<div class="ib-section-title">调试结果</div>', unsafe_allow_html=True)
                st.markdown(
                    '<div class="ib-section-copy">这里展示本次草稿 Prompt 的结果状态、命中内容和最终输出预览。</div>',
                    unsafe_allow_html=True,
                )
                render_status_chip(status)
                if status == "success":
                    st.success(f"调试成功：候选 {debug_result['candidate_count']} 条，命中 {len(debug_result['selected_items'])} 条。")
                elif status == "empty":
                    st.warning(f"调试结果为空：候选 {debug_result['candidate_count']} 条，但没有命中内容。")
                elif status == "empty_candidates":
                    st.warning("当前没有可调试的候选内容。")
                else:
                    st.error(f"调试失败：{debug_result.get('error', '未知错误')}")

                render_result_panel(title="草稿 Prompt", result=debug_result)
                st.markdown("</div>", unsafe_allow_html=True)

            st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
            st.markdown('<div class="ib-section-title">最近调试记录</div>', unsafe_allow_html=True)
            st.markdown(
                '<div class="ib-section-copy">这里保留最近 20 次草稿试跑或对比记录，方便管理员回看最近调过哪些板块、结果是更好还是更差。</div>',
                unsafe_allow_html=True,
            )
            if not prompt_debug_history:
                st.info("还没有调试记录。先运行一次草稿 Prompt 或做一次“当前 vs 草稿”对比。")
            else:
                history_preview = prompt_debug_history[:8]
                for item in history_preview:
                    mode_label = "草稿试跑" if item.get("mode") == "draft_run" else "当前 vs 草稿"
                    fallback_label = "内置样例" if item.get("using_fallback_candidates") else "真实 RSS"
                    st.markdown(
                        f"""
                        <div class="ib-panel" style="margin-top:12px; margin-bottom:0;">
                          <div class="ib-chip-row">
                            <span class="ib-chip ib-chip-neutral">{mode_label}</span>
                            <span class="ib-chip ib-chip-neutral">{item.get('category', '未命名板块')}</span>
                            <span class="ib-chip ib-chip-neutral">{fallback_label}</span>
                          </div>
                          <div style="font-weight:700; margin:8px 0 6px;">{item.get('created_at', '')}</div>
                          <div class="ib-section-copy" style="margin-bottom:6px;">
                            候选 {item.get('candidate_count', 0)} 条 | {render_history_status('草稿', item.get('draft_status'), item.get('draft_selected_count'))}
                          </div>
                          <div class="ib-section-copy" style="margin-bottom:0;">
                            {render_history_status('当前', item.get('saved_status'), item.get('saved_selected_count'))}
                          </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    excerpt = item.get("draft_prompt_excerpt", "").strip()
                    if excerpt:
                        st.caption(f"草稿摘要：{excerpt}")
                if len(prompt_debug_history) > len(history_preview):
                    st.caption(f"当前共保存 {len(prompt_debug_history)} 条记录，仅展开最近 {len(history_preview)} 条。")
            st.markdown("</div>", unsafe_allow_html=True)

    with tab4:
        st.subheader("RSS 源健康度")
        st.caption("缓存优先、手动刷新。优先帮助管理员判断：源是坏了、没更新，还是只是今天没有候选。")

        health_snapshot = load_health_cache(bot_dir)
        run_summary = parse_recent_run_summary(bot_log_path)

        header_col1, header_col2, header_col3 = st.columns([1.3, 1.0, 1.2])
        with header_col1:
            if st.button("🔄 立即刷新健康度", type="primary", use_container_width=True):
                with st.spinner("正在全量检查 RSS 源，请稍候..."):
                    health_snapshot = get_feed_health_snapshot(
                        config.get("feeds", {}),
                        bot_dir=bot_dir,
                        use_cache=False,
                        force_refresh=True,
                    )
                st.success("RSS 健康度已刷新。")
        with header_col2:
            only_problem_feeds = st.toggle("仅看异常/无更新", value=False)
        with header_col3:
            stale_7d_only = st.toggle("仅看 7 天未更新", value=False)

        if health_snapshot is None:
            st.info("当前还没有健康度缓存。点击“立即刷新健康度”后，控制台会生成第一份检查结果。")
        else:
            diagnosis_cards = build_no_push_diagnosis(
                health_snapshot=health_snapshot,
                run_summary=run_summary,
                configured_categories=list(config.get("feeds", {}).keys()),
            )
            if diagnosis_cards:
                st.markdown('<div class="ib-hero">', unsafe_allow_html=True)
                st.markdown('<div class="ib-eyebrow">No Push Diagnosis</div>', unsafe_allow_html=True)
                st.markdown('<div class="ib-title">为什么今天没推送？</div>', unsafe_allow_html=True)
                task_started = run_summary.get("task_started_at")
                task_copy = f"最近一次任务开始于 {task_started}。" if task_started else "已根据最近一次任务日志和当前健康度缓存生成诊断。"
                st.markdown(
                    f'<div class="ib-subtitle">{task_copy} 以下卡片按优先级排序，先处理靠前问题。</div>',
                    unsafe_allow_html=True,
                )
                st.markdown("</div>", unsafe_allow_html=True)
                for card in diagnosis_cards:
                    render_diagnosis_card(
                        card,
                        prompt_categories=list(config.get("feeds", {}).keys()),
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
                    f"检查时间：{format_timestamp(checked_at)} | 数据来源：{source_label} | 缓存年龄：{age_text} | 缓存文件：{feed_health_cache_file_path(bot_dir)}"
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

    with tab5:
        st.subheader("🕵️‍♂️ 深度运行日志追踪")
        st.caption("日志已开启企业级轮转模式（自动保留 30 天，每日切割）。在这里，你能看到AI到底看了哪些原文链接。")

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
                    last_lines = "".join(lines[-300:])
                st.code(last_lines, language="bash")
            except Exception as e:
                st.error(f"读取日志出错: {e}")
        else:
            st.info("暂无深度日志。请点击侧边栏【立即手动运行】生成第一份报告。")

    with tab6:
        st.subheader("➕ 添加源")
        st.caption("支持单条或批量添加，自动通过 RSSHub 检测并 RSS 化")

        # ---- 批量输入区 ----
        url_text = st.text_area(
            "网站 URL（支持批量，每行一个或用逗号分隔）",
            placeholder="https://example.com\nhttps://another.com\nhttps://third.com",
            height=120,
            key="batch_url_input"
        )

        col_mode, col_btn = st.columns([1, 4])
        with col_mode:
            st.write("")
        with col_btn:
            if st.button("🔍 批量检测", type="primary", use_container_width=True):
                if not url_text.strip():
                    st.warning("请输入至少一个 URL")
                else:
                    # 解析URL列表
                    raw_urls = url_text.strip().replace(",", "\n").split("\n")
                    urls = [u.strip() for u in raw_urls if u.strip()]

                    # 过滤有效URL
                    valid_urls, invalid_msgs = [], []
                    for u in urls:
                        if u.startswith("http://") or u.startswith("https://"):
                            valid_urls.append(u)
                        else:
                            invalid_msgs.append(f"⚠️ 无效格式已跳过: {u}")

                    for msg in invalid_msgs:
                        st.info(msg)

                    if not valid_urls:
                        st.error("没有找到有效的 URL（需以 http:// 或 https:// 开头）")
                    else:
                        resolver = UrlResolver()
                        results = []

                        progress_bar = st.progress(0)
                        status_text = st.empty()

                        for i, url in enumerate(valid_urls):
                            status_text.text(f"检测中 {i+1}/{len(valid_urls)}: {url[:50]}...")
                            result = resolver.resolve(url)
                            domain = url.split("://")[-1].split("/")[0]
                            results.append({
                                "original": url,
                                "domain": domain,
                                "status": result.status,
                                "feed_url": result.feed_url if result.status == "success" else None,
                                "reason": result.reason if result.status != "success" else None,
                            })
                            progress_bar.progress((i + 1) / len(valid_urls))

                        status_text.text("检测完成！")
                        st.session_state["batch_results"] = results

        # ---- 批量检测结果展示 ----
        if "batch_results" in st.session_state and st.session_state["batch_results"]:
            results = st.session_state["batch_results"]
            all_cats = list(load_config().get("feeds", {}).keys())

            st.markdown(f"#### 📋 检测结果（{len(results)} 个）")

            # 表头
            hdr_col1, hdr_col2, hdr_col3, hdr_col4 = st.columns([3, 1, 3, 1])
            with hdr_col1:
                st.markdown("**原始 URL**")
            with hdr_col2:
                st.markdown("**状态**")
            with hdr_col3:
                st.markdown("**RSS / 原因**")
            with hdr_col4:
                st.markdown("**板块**")

            st.markdown("---*")

            # 每行结果 + 分类选择
            if "batch_cats" not in st.session_state:
                st.session_state["batch_cats"] = {}

            any_success = False
            for idx, r in enumerate(results):
                col1, col2, col3, col4 = st.columns([3, 1, 3, 1])
                with col1:
                    display_url = r["original"][:60] + ("..." if len(r["original"]) > 60 else "")
                    st.text(display_url)
                with col2:
                    if r["status"] == "success":
                        st.markdown("✅ 成功")
                        any_success = True
                    else:
                        st.markdown(f"❌ 失败")
                with col3:
                    if r["status"] == "success":
                        st.text(r["feed_url"][:70] + ("..." if r["feed_url"] and len(r["feed_url"]) > 70 else ""))
                    else:
                        st.caption(r["reason"][:70] if r["reason"] else "未知原因")
                with col4:
                    if r["status"] == "success" and all_cats:
                        default_cat = st.session_state["batch_cats"].get(r["original"], all_cats[0])
                        sel = st.selectbox(
                            "板块",
                            options=all_cats,
                            index=all_cats.index(default_cat) if default_cat in all_cats else 0,
                            key=f"batch_cat_{idx}",
                            label_visibility="collapsed"
                        )
                        st.session_state["batch_cats"][r["original"]] = sel
                    elif r["status"] == "success":
                        st.warning("无板块")

            st.markdown("---*")

            # 批量订阅按钮
            if any_success and all_cats:
                col_sub, col_clr = st.columns([1, 4])
                with col_sub:
                    if st.button("📥 批量订阅", type="primary", use_container_width=True):
                        added, skipped, failed = 0, 0, 0
                        for r in results:
                            if r["status"] == "success":
                                cat = st.session_state["batch_cats"].get(r["original"], all_cats[0])
                                ok = add_rss_feed_to_config(r["feed_url"], cat, r["domain"])
                                if ok:
                                    added += 1
                                else:
                                    skipped += 1
                            else:
                                failed += 1

                        msg = f"添加 {added} 个源"
                        if skipped:
                            msg += f"，{skipped} 个已存在"
                        if failed:
                            msg += f"，{failed} 个失败"
                        st.success(msg)
                        st.session_state["batch_results"] = None
                        st.session_state["batch_cats"] = {}
                        st.rerun()

                with col_clr:
                    if st.button("🗑️ 清除结果", use_container_width=True):
                        st.session_state["batch_results"] = None
                        st.session_state["batch_cats"] = {}
                        st.rerun()
            elif not all_cats:
                st.warning("请先创建板块后再订阅")

        st.divider()


if __name__ == "__main__":
    main()
