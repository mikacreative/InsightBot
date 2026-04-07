#!/usr/bin/env python3
"""
debug_prompt.py — AI Prompt 调优专用工具

功能：
  - 针对单个板块，使用真实 AI API 测试 Prompt 效果
  - 输入：板块名称 + 自定义新闻列表（或从 RSS 实时抓取）
  - 输出：AI 的原始响应，方便快速迭代 Prompt

用法：
  set -a; source .env.local; set +a

  # 测试指定板块的 Prompt（使用本地内容配置中的 RSS 源实时抓取）
  python debug_prompt.py --category "📢 营销行业"

  # 使用自定义新闻列表测试（不需要 RSS 源）
  python debug_prompt.py --category "📢 营销行业" --mock-news

  # 测试修改后的 Prompt（临时覆盖，不修改 config 文件）
  python debug_prompt.py --category "📢 营销行业" --prompt "新的筛选标准：只保留有数据支撑的内容"
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import feedparser

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT))

from insightbot.ai import chat_completion
from insightbot.config import load_runtime_config
from insightbot.paths import config_content_file_path, config_file_path, default_bot_dir

# ── 模拟新闻数据（用于快速测试，不依赖 RSS 源）─────────────────────────────────
MOCK_NEWS_LIST = [
    {"title": "[RSS] 微信视频号广告 ROI 提升 30%，品牌主加速布局", "link": "https://example.com/001"},
    {"title": "[RSS] 小红书推出品牌号新功能：支持直链跳转电商平台", "link": "https://example.com/002"},
    {"title": "[RSS] AI 文案工具月活突破 500 万，营销效率提升显著", "link": "https://example.com/003"},
    {"title": "[RSS] 某明星离婚八卦新闻（无关内容，测试拦截）", "link": "https://example.com/004"},
    {"title": "[RSS] 国家队足球赛事直播（无关内容，测试拦截）", "link": "https://example.com/005"},
    {"title": "[RSS] 抖音电商 GMV 同比增长 45%，直播带货进入精细化运营阶段", "link": "https://example.com/006"},
]


def fetch_rss_news(rss_urls: list[str], logger) -> list[dict]:
    """从 RSS 源实时抓取近 24 小时的文章。"""
    candidates = []
    for url in rss_urls:
        url = url.split("#")[0].strip()
        if not url:
            continue
        try:
            logger.info(f"  抓取 RSS 源: {url}")
            feed = feedparser.parse(url)
            count = 0
            for entry in feed.entries:
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    dt = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                    if datetime.now() - dt > timedelta(hours=24):
                        continue
                candidates.append({"title": f"[RSS] {entry.title}", "link": entry.link})
                count += 1
            logger.info(f"  ✅ 抓取到 {count} 条有效文章")
        except Exception as e:
            logger.warning(f"  ⚠️ 抓取失败: {e}")
    return candidates


def build_prompt_input(category_name: str, news_list: list[dict]) -> str:
    """构建发送给 AI 的 user_text。"""
    input_text = f"【当前处理板块】：{category_name}\n【待筛选列表】：\n"
    for i, news in enumerate(news_list):
        clean_title = str(news.get("title", "")).replace("\n", " ")
        input_text += f"{i+1}. {clean_title} (Link: {news.get('link', '')})\n"
    return input_text


def main():
    parser = argparse.ArgumentParser(description="InsightBot Prompt 调优工具")
    parser.add_argument("--category", required=True, help="要测试的板块名称（需与 config 中一致）")
    parser.add_argument("--prompt", default=None, help="临时覆盖该板块的专属 Prompt（不修改 config 文件）")
    parser.add_argument("--mock-news", action="store_true", help="使用内置模拟新闻列表，不抓取 RSS")
    parser.add_argument("--temperature", type=float, default=0.1, help="AI temperature（默认 0.1）")
    args = parser.parse_args()

    # ── 初始化 logger ─────────────────────────────────────────────────────────
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    logger = logging.getLogger("PromptDebug")

    # ── 加载配置 ──────────────────────────────────────────────────────────────
    bot_dir = default_bot_dir()
    content_path = config_content_file_path(bot_dir)
    legacy_path = config_file_path(bot_dir)
    if not os.path.exists(content_path) and not os.path.exists(legacy_path):
        logger.error(f"找不到配置文件: {content_path}")
        sys.exit(1)
    config = load_runtime_config(bot_dir)

    # ── 查找目标板块 ──────────────────────────────────────────────────────────
    feeds = config.get("feeds", {})
    if args.category not in feeds:
        logger.error(f"板块 [{args.category}] 不存在于配置中。")
        logger.info(f"可用板块: {list(feeds.keys())}")
        sys.exit(1)

    feed_data = feeds[args.category]
    category_prompt = args.prompt if args.prompt is not None else feed_data.get("prompt", "")

    print("\n" + "=" * 60)
    print(f"  Prompt 调优测试")
    print(f"  板块: {args.category}")
    print(f"  模式: {'模拟数据' if args.mock_news else '实时 RSS 抓取'}")
    print(f"  Temperature: {args.temperature}")
    print("=" * 60)

    # ── 准备新闻列表 ──────────────────────────────────────────────────────────
    if args.mock_news:
        news_list = MOCK_NEWS_LIST
        logger.info(f"使用模拟新闻列表，共 {len(news_list)} 条")
    else:
        news_list = fetch_rss_news(feed_data.get("rss", []), logger)
        if not news_list:
            logger.warning("未抓取到任何文章，切换为模拟数据...")
            news_list = MOCK_NEWS_LIST

    # ── 构建完整 System Prompt ────────────────────────────────────────────────
    system_prompt = config["ai"]["system_prompt"]
    if category_prompt:
        system_prompt += f"\n\n【本板块专属内容标准】：\n{category_prompt}"
    system_prompt += """\n\n【系统最高强制指令】(覆盖上述所有规则)：
1. 宁缺毋滥：如果列表里没有任何符合标准的新闻，你必须、且只能回复四个英文字母：NONE。绝对不允许向用户解释原因，不允许说任何多余的话！
2. 格式红线：只要你输出了新闻摘要，标题必须严格包含原文URL，使用格式：### [重写后的精简标题](原文Link)。绝对不允许丢失链接！"""

    user_text = build_prompt_input(args.category, news_list)

    print(f"\n📋 喂给 AI 的新闻列表（共 {len(news_list)} 条）:")
    for i, news in enumerate(news_list):
        print(f"  {i+1}. {news['title'][:60]}...")

    print(f"\n🧠 使用的板块专属 Prompt:")
    print(f"  {category_prompt or '（无专属 Prompt）'}")

    print(f"\n⏳ 正在调用 AI API...")

    # ── 调用 AI ───────────────────────────────────────────────────────────────
    start_time = time.time()
    try:
        result = chat_completion(
            api_url=config["ai"]["api_url"],
            api_key=config["ai"]["api_key"],
            model=config["ai"]["model"],
            system_prompt=system_prompt,
            user_text=user_text[:15000],
            temperature=args.temperature,
            timeout_s=120,
        )
        elapsed = time.time() - start_time

        print(f"\n✅ AI 响应（耗时 {elapsed:.1f}s）:")
        print("─" * 60)
        if result == "NONE" or "NONE" in result:
            print("  🈳 AI 判定：无合格内容（返回 NONE）")
            print("  → 建议：放宽板块专属 Prompt 的筛选标准，或检查新闻列表是否相关。")
        else:
            print(result)
        print("─" * 60)

    except Exception as e:
        logger.error(f"AI 调用失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
