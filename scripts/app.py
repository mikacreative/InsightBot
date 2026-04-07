import json
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
    st.title("🚀 营销情报站 | 智控中心")
    st.caption(f"当前编辑配置文件: {active_edit_path}")

    if "settings" not in config:
        config["settings"] = {}

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
        st.text_area("System Prompt (系统提示词)", value=ai_conf.get("system_prompt", ""), height=300, key="sys_prompt")
        col1, col2 = st.columns(2)
        with col1:
            st.text_input("AI Model", value=ai_conf.get("model", ""), key="ai_model")
        with col2:
            st.text_input("API URL", value=ai_conf.get("api_url", ""), key="ai_url")
        masked_api_key = runtime_ai.get("api_key", "")
        if masked_api_key:
            st.caption(f"API Key 来源于 secrets / 环境变量：{masked_api_key[:6]}...{masked_api_key[-4:]}")
        else:
            st.warning("当前未检测到 AI API Key。请在 config.secrets.json 或环境变量中配置。")

        if st.button("💾 更新 AI 大脑"):
            config["ai"]["system_prompt"] = st.session_state.sys_prompt
            config["ai"]["model"] = st.session_state.ai_model
            config["ai"]["api_url"] = st.session_state.ai_url
            save_config(config)
            st.toast("AI 内容配置更新成功！敏感信息请通过 secrets 或环境变量维护。")

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
