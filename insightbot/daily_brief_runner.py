import os
import time
from datetime import datetime, timedelta

import feedparser

from .ai import chat_completion
from .wecom import send_markdown_to_app


def run_daily_brief(
    *,
    cid: str,
    secret: str,
    agent_id: str,
    api_url: str,
    api_key: str,
    model: str,
    feeds: dict[str, list[str]],
    logger,
) -> None:
    logger.info(f"开始任务: {datetime.now()}")

    report = f"# 📅 营销早报 | {datetime.now().strftime('%m-%d')}\n"
    has_update = False

    for category, urls in feeds.items():
        cat_content = ""
        for url in urls:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries:
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        dt = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                        if datetime.now() - dt > timedelta(hours=24):
                            continue

                    text = entry.get("summary", "") or entry.title
                    summary = chat_completion(
                        api_url=api_url,
                        api_key=api_key,
                        model=model,
                        system_prompt="你是一个营销情报官。请将新闻总结为一句话(50字内)，包含事实与对营销行业的影响。",
                        user_text=str(text)[:800],
                        temperature=0.2,
                        timeout_s=20,
                    )
                    cat_content += f"> **[{entry.title}]({entry.link})**\n> <font color='comment'>{summary}</font>\n\n"
                    has_update = True
                    if len(cat_content) > 1000:
                        break
            except Exception as e:
                logger.warning(f"Error fetching {url}: {e}")

        if cat_content:
            report += f"\n## {category}\n{cat_content}"

    if has_update:
        ok = send_markdown_to_app(
            cid=cid,
            secret=secret,
            agent_id=agent_id,
            content=report,
        )
        logger.info("推送成功" if ok else "推送失败")
    else:
        logger.info("今日无更新，不推送")

