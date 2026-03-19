import json
import time
from datetime import datetime, timedelta

import feedparser

from .ai import chat_completion
from .wecom import send_markdown_to_app


def _ai_process_category(*, config: dict, category_name: str, news_list: list[dict], category_prompt: str, logger):
    if not news_list:
        return None

    input_text = f"【当前处理板块】：{category_name}\n【待筛选列表】：\n"
    for i, news in enumerate(news_list):
        clean_title = str(news.get("title", "")).replace("\n", " ")
        input_text += f"{i+1}. {clean_title} (Link: {news.get('link','')})\n"

    final_system_prompt = config["ai"]["system_prompt"]
    if category_prompt:
        final_system_prompt += f"\n\n【本板块专属内容标准】：\n{category_prompt}"

    final_system_prompt += """\n\n【系统最高强制指令】(覆盖上述所有规则)：
1. 宁缺毋滥：如果列表里没有任何符合标准的新闻，你必须、且只能回复四个英文字母：NONE。绝对不允许向用户解释原因，不允许说任何多余的话！
2. 格式红线：只要你输出了新闻摘要，标题必须严格包含原文URL，使用格式：### [重写后的精简标题](原文Link)。绝对不允许丢失链接！"""

    logger.info(f"🤖 开始呼叫 AI 分析 [{category_name}] (共 {len(news_list)} 条信源喂给AI)")

    max_retries = 3
    for attempt in range(max_retries):
        try:
            result_text = chat_completion(
                api_url=config["ai"]["api_url"],
                api_key=config["ai"]["api_key"],
                model=config["ai"]["model"],
                system_prompt=final_system_prompt,
                user_text=input_text[:15000],
                temperature=0.1,
                timeout_s=120,
            )
            if result_text == "NONE" or "NONE" in result_text:
                logger.info(f"🈳 AI 判定 [{category_name}] 无合格内容，已拦截。")
                return None
            return result_text
        except Exception as e:
            logger.warning(f"⚠️ AI 分析第 {attempt + 1} 次尝试失败 [{category_name}]: {e}")
            if attempt < max_retries - 1:
                time.sleep(5)
            else:
                logger.error(f"❌ AI 分析彻底失败 [{category_name}]")
                return None


def run_task(*, config: dict, logger) -> None:
    logger.info("=" * 40)
    logger.info("🚀 === 营销情报抓取任务开始 ===")
    logger.info("=" * 40)

    settings = config.get("settings", {})

    today_str = datetime.now().strftime("%m-%d")
    title_template = settings.get("report_title", "📅 营销情报早报 | {date}")
    header_msg = f"# {title_template.replace('{date}', today_str)}\n> 正在为您通过 AI 融合检索定向信源与全网热词..."
    send_markdown_to_app(
        cid=config["wecom"]["cid"],
        secret=config["wecom"]["secret"],
        agent_id=str(config["wecom"]["aid"]),
        content=header_msg,
    )

    has_any_update = False

    for category, feed_data in config.get("feeds", {}).items():
        logger.info(f"\n📁 正在处理板块: 【{category}】")
        category_candidates: list[dict] = []

        rss_urls = feed_data.get("rss", [])
        for raw_url in rss_urls:
            url = str(raw_url).split("#")[0].strip()
            if not url:
                continue
            try:
                feed = feedparser.parse(url)
                valid_count = 0
                for entry in feed.entries:
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        dt = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                        if datetime.now() - dt > timedelta(hours=24):
                            continue

                    category_candidates.append({"title": f"[RSS] {entry.title}", "link": entry.link})
                    valid_count += 1
                    logger.info(f"  📥 抓取命中 -> {entry.title} ({entry.link})")

                logger.info(f"✅ RSS源 [{url}] 抓取完成，共获得 {valid_count} 条有效资讯")
            except Exception as e:
                logger.error(f"⚠️ RSS抓取失败 [{url}]: {e}")

        # 关键词接口预留（保持与原逻辑一致：当前休眠）
        keywords = feed_data.get("keywords", [])
        if keywords:
            pass

        if category_candidates:
            seen_links: set[str] = set()
            unique_candidates: list[dict] = []
            for item in category_candidates:
                link = str(item.get("link", ""))
                if link and link not in seen_links:
                    unique_candidates.append(item)
                    seen_links.add(link)

            logger.info(f"⏳ 板块 【{category}】 排重后剩余 {len(unique_candidates)} 条数据交由 AI 筛选...")
            ai_summary = _ai_process_category(
                config=config,
                category_name=category,
                news_list=unique_candidates,
                category_prompt=feed_data.get("prompt", ""),
                logger=logger,
            )

            if ai_summary:
                msg_body = f"## {category}\n{ai_summary}"
                logger.info(f"📤 推送板块 【{category}】 成功")
                send_markdown_to_app(
                    cid=config["wecom"]["cid"],
                    secret=config["wecom"]["secret"],
                    agent_id=str(config["wecom"]["aid"]),
                    content=msg_body,
                )
                has_any_update = True
                time.sleep(2)
        else:
            logger.info(f"📭 板块 【{category}】 今日无更新数据")

    if has_any_update:
        if settings.get("show_footer", True):
            send_markdown_to_app(
                cid=config["wecom"]["cid"],
                secret=config["wecom"]["secret"],
                agent_id=str(config["wecom"]["aid"]),
                content=f"\n{settings.get('footer_text', '')}",
            )
        logger.info("✅ 任务圆满完成")
    else:
        empty_msg = settings.get("empty_message", "📭 今日全网无重要更新。")
        send_markdown_to_app(
            cid=config["wecom"]["cid"],
            secret=config["wecom"]["secret"],
            agent_id=str(config["wecom"]["aid"]),
            content=empty_msg,
        )
        logger.info("📭 今日全网无更新内容被推送")

