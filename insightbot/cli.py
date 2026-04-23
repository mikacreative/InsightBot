"""
InsightBot CLI entrypoint.

Usage:
    insightbot              — start scheduler daemon (runs all enabled tasks on schedule)
    insightbot --task ID    — run a specific task immediately
    insightbot --dry-run ID — dry run a task (no channel sends, prints result to stdout)
    insightbot --webhook    — start WeChat Work webhook server
"""

import argparse
import json
import sys

from .channels import init_channels
from .config import load_channels
from .logging_setup import build_logger
from .paths import bot_log_file_path, default_bot_dir
from .scheduler import create_scheduler


def main() -> None:
    parser = argparse.ArgumentParser(prog="insightbot", description="InsightBot CLI")
    parser.add_argument(
        "--task",
        help="Run a specific task by ID immediately (bypasses schedule)",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Dry run: execute pipeline but do not send to any channel",
    )
    parser.add_argument(
        "--webhook",
        action="store_true",
        help="Start WeChat Work webhook server (port 8080)",
    )
    args = parser.parse_args()

    bot_dir = default_bot_dir()
    log_path = bot_log_file_path(bot_dir)
    logger = build_logger("InsightBot", log_path)

    # Initialize channels from channels.json
    channels_data = load_channels(bot_dir)
    init_channels(channels_data)

    # Create scheduler (auto-migrates v1 config if needed)
    scheduler = create_scheduler(bot_dir)

    if args.webhook:
        from .wecom_callback import start_webhook_server

        logger.info("Starting WeChat Work webhook server...")
        start_webhook_server(port=8080, scheduler=scheduler)
        sys.exit(0)

    if args.task:
        # Run a specific task immediately
        result = scheduler.run_task_by_id(args.task, dry_run=args.dry_run)
        logger.info(
            f"Task '{args.task}' completed: ok={result.get('ok')}, "
            f"dry_run={args.dry_run}"
        )
        if args.dry_run:
            print(
                json.dumps(
                    {
                        "ok": result.get("ok"),
                        "task_id": result.get("task_id"),
                        "pipeline": result.get("pipeline"),
                        "final_markdown": result.get("final_markdown"),
                        "stage_results": result.get("stage_results"),
                        "error": result.get("error"),
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
        sys.exit(0 if result.get("ok") else 1)
    else:
        # Run as scheduler daemon
        logger.info("=" * 50)
        logger.info("InsightBot scheduler starting...")
        logger.info("Press Ctrl+C to stop.")
        logger.info("=" * 50)
        scheduler.run_loop()


if __name__ == "__main__":
    main()
