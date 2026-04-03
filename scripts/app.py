import json
import os
import subprocess
import sys
from datetime import datetime

import streamlit as st
from crontab import CronTab

from insightbot.paths import bot_log_file_path, config_file_path, cron_log_file_path, default_bot_dir
from insightbot.discovery_service import DiscoveryService
from insightbot.discovery.url_resolver import UrlResolver


def main() -> None:
    bot_dir = default_bot_dir()
    config_path = config_file_path(bot_dir)
    cron_log_path = cron_log_file_path(bot_dir)
    bot_log_path = bot_log_file_path(bot_dir)

    smart_brief_path = os.getenv("SMART_BRIEF_PATH", os.path.join(bot_dir, "smart_brief.py"))
    smart_brief_mode = os.getenv("SMART_BRIEF_MODE", "script").strip().lower()  # script | module

    def load_config() -> dict:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_config(config: dict) -> None:
        with open(config_path, "w", encoding="utf-8") as f:
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

    st.set_page_config(page_title="营销情报站 | 控制台", layout="wide")
    st.title("🚀 营销情报站 | 智控中心")

    config = load_config()
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
        st.text_area("System Prompt (系统提示词)", value=ai_conf.get("system_prompt", ""), height=300, key="sys_prompt")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.text_input("AI Model", value=ai_conf.get("model", ""), key="ai_model")
        with col2:
            st.text_input("API Key", value=ai_conf.get("api_key", ""), type="password", key="ai_key")
        with col3:
            st.text_input("API URL", value=ai_conf.get("api_url", ""), key="ai_url")

        if st.button("💾 更新 AI 大脑"):
            config["ai"]["system_prompt"] = st.session_state.sys_prompt
            config["ai"]["model"] = st.session_state.ai_model
            config["ai"]["api_key"] = st.session_state.ai_key
            config["ai"]["api_url"] = st.session_state.ai_url
            save_config(config)
            st.toast("AI 配置更新成功！")

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
        st.caption("输入任意网站 URL，RSSHub 会自动尝试 RSS 化")

        # ---- 添加源输入区 ----
        col_input, col_btn = st.columns([4, 1])
        with col_input:
            url_input = st.text_input(
                "网站 URL",
                placeholder="https://example.com",
                label_visibility="collapsed",
                key="url_add_input"
            )

        resolve_triggered = False
        with col_btn:
            st.write("")  # 对齐
            if st.button("🔍 检测", type="primary", use_container_width=True):
                resolve_triggered = True

        # ---- 检测结果展示 ----
        if resolve_triggered and url_input:
            url_clean = url_input.strip()
            if not url_clean.startswith("http"):
                st.error("请输入以 http:// 或 https:// 开头的完整 URL")
            else:
                with st.spinner("正在通过 RSSHub 检测..."):
                    resolver = UrlResolver()
                    result = resolver.resolve(url_clean)

                if result.status == "success":
                    feed_url = result.feed_url
                    st.success(f"✅ 找到 RSS: {feed_url}")
                    
                    # 选择板块
                    all_cats = list(load_config().get("feeds", {}).keys())
                    if all_cats:
                        cat_col, btn_col = st.columns([2, 1])
                        with cat_col:
                            sel_cat = st.selectbox("添加到板块", options=all_cats, key="url_sel_cat")
                        with btn_col:
                            st.write("")
                            if st.button("📥 订阅", type="primary"):
                                domain = url_clean.split("://")[-1].split("/")[0]
                                ok = add_rss_feed_to_config(feed_url, sel_cat, domain)
                                if ok:
                                    st.success(f"已添加到「{sel_cat}」")
                                else:
                                    st.info("该源已在列表中")
                    else:
                        st.warning("请先创建板块")
                else:
                    st.error(f"❌ 检测失败: {result.reason}")
                    st.info("提示：部分网站 RSSHub 确实无法转换，建议寻找该站的 RSS 源直接添加")

        st.divider()

        # ---- 原有推荐池管理（保留）----
        st.subheader("🔍 智能推荐池")
        st.caption("系统自动发现的候选 RSS 源")

        try:
            service = DiscoveryService(config_path=config_path)
        except Exception as e:
            st.error(f"初始化失败: {e}")
            service = None

        if service:
            status = service.get_pool_status()

            # 状态栏
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                en = st.toggle("🟢 自动发现", value=status["enabled"], key="disc_toggle")
                if en != status["enabled"]:
                    service.set_enabled(en)
                    st.rerun()
            with c2:
                st.metric("待处理", status["pending"])
            with c3:
                st.metric("已采纳", status["approved"])
            with c4:
                st.metric("池容量", f"{status['pool_current']}/{status['pool_max']}")

            if st.button("🚀 运行发现"):
                with st.spinner("运行中..."):
                    added = service.run_discovery()
                st.success(f"新增 {added} 个")
                st.rerun()

            # 推荐池列表
            pending = service.get_pending_feeds()
            if pending:
                st.markdown("#### 待处理推荐")
                for feed in pending[:5]:
                    url = feed.get("feed_url", "")
                    col_url, col_cat, col_btn = st.columns([3, 2, 1])
                    with col_url:
                        st.text(url[:50] + "..." if len(url) > 50 else url)
                    with col_cat:
                        cats = list(load_config().get("feeds", {}).keys())
                        sel = st.selectbox("板块", [""] + cats, key=f"pend_{hash(url)}", label_visibility="collapsed")
                    with col_btn:
                        if sel and st.button("✅", key=f"app_{hash(url)}"):
                            service.approve(url, sel)
                            st.rerun()
            else:
                st.info("推荐池为空")


if __name__ == "__main__":
    main()

