#!/usr/bin/env python3
"""
debug_rss_check.py — RSS 信源健康度检查工具

功能：
  - 检查当前内容配置中的所有 RSS 源可达性
  - 统计每个源的文章数量和最新文章时间
  - 标记出无法访问或长时间无更新的信源

用法：
  set -a; source .env.local; set +a
  python debug_rss_check.py
"""
import os
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT))

from insightbot.config import load_runtime_config
from insightbot.feed_health import get_feed_health_snapshot
from insightbot.paths import config_content_file_path, config_file_path, default_bot_dir


def main():
    bot_dir = default_bot_dir()
    content_path = config_content_file_path(bot_dir)
    legacy_path = config_file_path(bot_dir)

    if not os.path.exists(content_path) and not os.path.exists(legacy_path):
        print(f"❌ 找不到配置文件: {content_path}")
        sys.exit(1)

    config = load_runtime_config(bot_dir)
    feeds = config.get("feeds", {})

    print("\n" + "=" * 70)
    print("  InsightBot RSS 信源健康度检查")
    print(f"  检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    snapshot = get_feed_health_snapshot(feeds, bot_dir=bot_dir, use_cache=False, force_refresh=True)

    for category_result in snapshot["categories"]:
        print(f"\n📂 板块: {category_result['category']}（共 {category_result['feed_count']} 个信源）")

        for result in category_result["feeds"]:
            print(f"  🔍 检查: {result['url'][:70]}...")

            if result["status"] == "error":
                print(f"  ❌ 状态: 错误 [{result.get('error_type')}] — {result.get('error_message')}")
            elif result["status"] == "stale":
                print(f"  ⚠️  状态: 可达，但近 24h 无更新（共 {result['total_entries']} 篇文章）")
                if result["latest_pub"]:
                    latest_dt = datetime.fromisoformat(result["latest_pub"])
                    print(f"       最新文章时间: {latest_dt.strftime('%Y-%m-%d %H:%M')}")
            else:
                elapsed_str = f"，响应 {result.get('elapsed_s', '?')}s" if result.get("elapsed_s") is not None else ""
                print(f"  ✅ 状态: 正常{elapsed_str}")
                print(f"       近 24h: {result['recent_entries']} 篇 / 共 {result['total_entries']} 篇")
                if result["latest_pub"]:
                    latest_dt = datetime.fromisoformat(result["latest_pub"])
                    print(f"       最新文章: {latest_dt.strftime('%Y-%m-%d %H:%M')}")

    print("\n" + "─" * 70)
    counts = snapshot["counts"]
    print(f"  检查结果汇总: ✅ 正常 {counts['ok']}  ⚠️ 无更新 {counts['stale']}  ❌ 错误 {counts['error']}")
    if counts["error"] > 0:
        print("  建议：检查错误信源的 URL 是否正确，或本地 Docker 服务是否运行。")
    if counts["stale"] > 0:
        print("  建议：无更新的信源可能是今日确实无新内容，或 RSS 源更新频率较低。")
    print("─" * 70 + "\n")


if __name__ == "__main__":
    main()
