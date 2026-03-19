#!/usr/bin/env python3
"""
debug_rss_check.py — RSS 信源健康度检查工具

功能：
  - 检查 config.local.json 中所有 RSS 源的可达性
  - 统计每个源的文章数量和最新文章时间
  - 标记出无法访问或长时间无更新的信源

用法：
  set -a; source .env.local; set +a
  python debug_rss_check.py
"""
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import feedparser

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT))

from insightbot.config import load_json_config
from insightbot.paths import config_file_path, default_bot_dir


def check_feed(url: str) -> dict:
    """检查单个 RSS 源的状态，返回检查结果字典。"""
    result = {
        "url": url,
        "status": "unknown",
        "total_entries": 0,
        "recent_entries": 0,  # 24h 内
        "latest_pub": None,
        "error": None,
    }
    try:
        start = time.time()
        feed = feedparser.parse(url)
        elapsed = time.time() - start

        if feed.bozo and not feed.entries:
            result["status"] = "error"
            result["error"] = str(feed.bozo_exception) if feed.bozo_exception else "解析失败"
            return result

        result["total_entries"] = len(feed.entries)
        result["status"] = "ok"
        result["elapsed_s"] = round(elapsed, 2)

        latest_dt = None
        for entry in feed.entries:
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                dt = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                if latest_dt is None or dt > latest_dt:
                    latest_dt = dt
                if datetime.now() - dt <= timedelta(hours=24):
                    result["recent_entries"] += 1

        result["latest_pub"] = latest_dt

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result


def main():
    bot_dir = default_bot_dir()
    config_path = config_file_path(bot_dir)

    if not os.path.exists(config_path):
        print(f"❌ 找不到配置文件: {config_path}")
        sys.exit(1)

    config = load_json_config(config_path)
    feeds = config.get("feeds", {})

    print("\n" + "=" * 70)
    print("  InsightBot RSS 信源健康度检查")
    print(f"  检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    total_ok = 0
    total_warn = 0
    total_error = 0

    for category, feed_data in feeds.items():
        rss_urls = feed_data.get("rss", [])
        print(f"\n📂 板块: {category}（共 {len(rss_urls)} 个信源）")

        for raw_url in rss_urls:
            url = raw_url.split("#")[0].strip()
            if not url:
                continue

            print(f"  🔍 检查: {url[:70]}...")
            result = check_feed(url)

            if result["status"] == "error":
                print(f"  ❌ 状态: 错误 — {result['error']}")
                total_error += 1
            elif result["recent_entries"] == 0:
                print(f"  ⚠️  状态: 可达，但近 24h 无更新（共 {result['total_entries']} 篇文章）")
                if result["latest_pub"]:
                    print(f"       最新文章时间: {result['latest_pub'].strftime('%Y-%m-%d %H:%M')}")
                total_warn += 1
            else:
                elapsed_str = f"，响应 {result.get('elapsed_s', '?')}s" if "elapsed_s" in result else ""
                print(f"  ✅ 状态: 正常{elapsed_str}")
                print(f"       近 24h: {result['recent_entries']} 篇 / 共 {result['total_entries']} 篇")
                if result["latest_pub"]:
                    print(f"       最新文章: {result['latest_pub'].strftime('%Y-%m-%d %H:%M')}")
                total_ok += 1

    print("\n" + "─" * 70)
    print(f"  检查结果汇总: ✅ 正常 {total_ok}  ⚠️ 无更新 {total_warn}  ❌ 错误 {total_error}")
    if total_error > 0:
        print("  建议：检查错误信源的 URL 是否正确，或本地 Docker 服务是否运行。")
    if total_warn > 0:
        print("  建议：无更新的信源可能是今日确实无新内容，或 RSS 源更新频率较低。")
    print("─" * 70 + "\n")


if __name__ == "__main__":
    main()
