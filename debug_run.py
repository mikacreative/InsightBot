#!/usr/bin/env python3
"""
debug_run.py — InsightBot 本地调试入口脚本

功能：
  - 完整执行 RSS 抓取 + AI 筛选流程
  - 根据环境变量 DRY_RUN 决定是否实际推送企业微信
    · DRY_RUN=1（默认）：将生成的报告输出到本地 Markdown 文件，不推送
    · DRY_RUN=0：正常推送到企业微信（使用 .env.local 中的测试 Agent）

用法：
  # 加载本地环境变量后运行（推荐）
  set -a; source .env.local; set +a
  python debug_run.py

  # 或直接指定变量
  DRY_RUN=1 CONFIG_FILE=./config.local.json python debug_run.py
"""
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

# ── 确保从仓库根目录运行时能找到 insightbot 包 ────────────────────────────────
REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT))

from insightbot.config import load_json_config
from insightbot.logging_setup import build_logger
from insightbot.paths import bot_log_file_path, config_file_path, default_bot_dir
from insightbot.smart_brief_runner import run_task


def _build_console_only_logger(name: str) -> logging.Logger:
    """构建一个只输出到控制台的 logger，用于调试时的清晰输出。"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    )
    logger.addHandler(handler)
    return logger


def _dry_run_send(*, cid, secret, agent_id, content, touser="@all", timeout_s=10):
    """
    dry_run 模式下替换 send_markdown_to_app 的 Mock 函数。
    将消息内容追加到本地报告文件，并在控制台打印预览。
    """
    output_path = os.getenv("DRY_RUN_OUTPUT", "./logs_local/dry_run_report.md")
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    separator = "\n\n---\n\n"
    with open(output_path, "a", encoding="utf-8") as f:
        f.write(content + separator)

    # 控制台预览（截取前 200 字符）
    preview = content[:200].replace("\n", " ")
    print(f"\n  [DRY_RUN] 📝 消息已写入本地文件（预览）: {preview}...")
    return True


def main():
    dry_run = os.getenv("DRY_RUN", "1").strip() == "1"

    print("=" * 60)
    print(f"  InsightBot 本地调试运行")
    print(f"  模式: {'🔒 DRY_RUN（不推送企业微信）' if dry_run else '🚀 LIVE（真实推送）'}")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # ── 加载配置 ──────────────────────────────────────────────────────────────
    bot_dir = default_bot_dir()
    config_path = config_file_path(bot_dir)

    if not os.path.exists(config_path):
        print(f"\n❌ 错误：找不到配置文件 [{config_path}]")
        print("   请先执行：cp config.local.example.json config.local.json")
        print("   并填写真实的 API Key 和企业微信凭证。")
        sys.exit(1)

    config = load_json_config(config_path)
    print(f"\n✅ 已加载配置文件: {config_path}")
    print(f"   板块数量: {len(config.get('feeds', {}))}")
    print(f"   AI 模型: {config.get('ai', {}).get('model', '未配置')}")

    # ── 构建 logger ───────────────────────────────────────────────────────────
    if dry_run:
        logger = _build_console_only_logger("InsightBot.DebugRun")
    else:
        log_path = bot_log_file_path(bot_dir)
        logger = build_logger("InsightBot.DebugRun", log_path)

    # ── 清空上一次的 dry_run 报告 ─────────────────────────────────────────────
    if dry_run:
        output_path = os.getenv("DRY_RUN_OUTPUT", "./logs_local/dry_run_report.md")
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(f"# InsightBot DRY_RUN 报告\n\n**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n---\n\n")
        print(f"\n📄 报告将输出至: {output_path}")

    print("\n" + "─" * 60)

    # ── 执行任务 ──────────────────────────────────────────────────────────────
    if dry_run:
        with patch("insightbot.smart_brief_runner.send_markdown_to_app", side_effect=_dry_run_send):
            run_task(config=config, logger=logger)
    else:
        run_task(config=config, logger=logger)

    print("\n" + "─" * 60)
    if dry_run:
        output_path = os.getenv("DRY_RUN_OUTPUT", "./logs_local/dry_run_report.md")
        print(f"\n✅ 调试运行完成！报告已保存至: {output_path}")
        print("   使用任意 Markdown 查看器打开即可预览推送效果。")
    else:
        print("\n✅ 实时运行完成！请检查企业微信是否收到推送。")


if __name__ == "__main__":
    main()
