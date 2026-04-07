import json
import logging
import os
import subprocess
import sys
from datetime import datetime

import streamlit as st
from crontab import CronTab

from insightbot.config import load_runtime_config
from insightbot.paths import (
    bot_log_file_path,
    config_content_file_path,
    config_file_path,
    cron_log_file_path,
    default_bot_dir,
)
from insightbot.discovery.url_resolver import UrlResolver
from insightbot.smart_brief_runner import DEBUG_SAMPLE_NEWS, fetch_recent_candidates, run_prompt_debug

def main() -> None:
    bot_dir = default_bot_dir()
    content_config_path = config_content_file_path(bot_dir)
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

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 板块与信源管理", "⚙️ 推送版式定制", "🧠 AI 提示词调优", "📝 运行日志", "🔍 信源发现"])

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
            st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
            st.markdown('<div class="ib-section-title">运行时 AI 连接</div>', unsafe_allow_html=True)
            st.markdown(
                '<div class="ib-section-copy">这些值来自 secrets 或环境变量。控制台只展示，不允许直接编辑。</div>',
                unsafe_allow_html=True,
            )
            st.text_input("AI Model", value=runtime_ai.get("model", ""), disabled=True)
            st.text_input("API URL", value=runtime_ai.get("api_url", ""), disabled=True)
            masked_api_key = runtime_ai.get("api_key", "")
            if masked_api_key:
                st.caption(f"API Key：{masked_api_key[:6]}...{masked_api_key[-4:]}")
            else:
                st.warning("当前未检测到 AI API Key。请在 config.secrets.json 或环境变量中配置。")
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

            action_col1, action_col2, action_col3 = st.columns(3)
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
                        st.session_state["prompt_debug_result"] = debug_result
                        st.session_state["prompt_debug_result_category"] = selected_category

            with action_col3:
                if st.button("↩️ 草稿覆盖到编辑区", use_container_width=True):
                    feeds[selected_category]["prompt"] = st.session_state[draft_key].strip()
                    config["feeds"] = feeds
                    save_config(config)
                    st.toast(f"已将草稿 Prompt 写回 [{selected_category}]。")
                    st.rerun()

            candidates = st.session_state.get("prompt_debug_candidates", [])
            meta = st.session_state.get("prompt_debug_meta", {})
            debug_result = st.session_state.get("prompt_debug_result")
            result_matches_category = debug_result and st.session_state.get("prompt_debug_result_category") == selected_category
            if candidates and meta.get("category") == selected_category:
                st.markdown('<div class="ib-panel">', unsafe_allow_html=True)
                st.markdown('<div class="ib-section-title">候选池</div>', unsafe_allow_html=True)
                st.markdown(
                    '<div class="ib-section-copy">这里是本次调试会送进 AI 的原始候选内容。先确认候选池质量，再判断 Prompt 是否合理。</div>',
                    unsafe_allow_html=True,
                )
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

            if result_matches_category:
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

                selected_items = debug_result.get("selected_items", [])
                if selected_items:
                    with st.expander("命中内容详情", expanded=True):
                        for idx, item in enumerate(selected_items, start=1):
                            title = item.get("title", "").strip()
                            url = item.get("url", "").strip()
                            summary = item.get("summary", "").strip()
                            st.markdown(f"**{idx}. [{title}]({url})**")
                            st.caption(summary or "无摘要")

                preview_md = debug_result.get("preview_markdown", "")
                preview_col1, preview_col2 = st.columns([1.2, 0.9])
                with preview_col1:
                    if preview_md:
                        st.markdown("**管理员预览输出**")
                        st.markdown(preview_md)
                    else:
                        st.info("本次没有生成可预览输出。")

                with preview_col2:
                    with st.expander("批次调试详情", expanded=status != "success"):
                        st.json(
                            {
                                "status": status,
                                "selected_items": selected_items,
                                "batches": debug_result.get("batches", []),
                            },
                            expanded=False,
                        )
                st.markdown("</div>", unsafe_allow_html=True)

    with tab4:
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

    with tab5:
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
