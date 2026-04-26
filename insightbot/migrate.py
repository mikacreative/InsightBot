"""
v1 → v2 migration.

Automatically called on first v2.0 boot if tasks.json does not exist.
Reads existing config.content.json + config.secrets.json and generates:
  - channels.json  (WeCom credentials extracted from secrets)
  - tasks.json    (default "daily_brief" task from existing feeds/config)
"""

import logging
import os

from .config import load_runtime_config, save_channels, save_tasks
from .paths import channels_file_path, tasks_file_path, default_bot_dir

logger = logging.getLogger("Migration")


def migrate_from_v1(bot_dir: str | None = None) -> None:
    """
    Generate channels.json and tasks.json from existing v1 configuration.
    Safe to call multiple times — only migrates if files don't exist.
    """
    bot_dir = bot_dir or default_bot_dir()
    channels_path = channels_file_path(bot_dir)
    tasks_path = tasks_file_path(bot_dir)

    # Skip if already migrated
    if os.path.exists(channels_path) and os.path.exists(tasks_path):
        logger.info("Migration already complete, skipping.")
        return

    logger.info("Running v1 → v2 migration...")
    config = load_runtime_config(bot_dir)

    # --- channels.json ---
    wecom = config.get("wecom", {})
    channels = {
        "channels": {
            "wecom_main": {
                "type": "wecom",
                "name": "主频道",
                "cid": wecom.get("cid", ""),
                "secret": wecom.get("secret", ""),
                "agent_id": str(wecom.get("aid", "")),
            }
        }
    }
    save_channels(channels, bot_dir)
    logger.info("channels.json generated.")

    # --- tasks.json ---
    feeds = config.get("feeds", {})
    editorial_config = (config.get("ai", {}) or {}).get("editorial_pipeline", {})
    search_config = config.get("search", {})

    # Derive schedule from system cron if possible (default to 8:00 AM)
    schedule = {"hour": 8, "minute": 0}

    task_def = {
        "name": "每日营销早报",
        "enabled": True,
        "feeds": feeds,
        "pipeline": "editorial" if editorial_config.get("enabled") else "classic",
        "_editorial_pipeline_mode": "legacy",  # "legacy" | "editorial-intelligence"
        "pipeline_config": {
            "global_shortlist_multiplier": editorial_config.get("global_shortlist_multiplier", 3),
            "allow_multi_assign": editorial_config.get("allow_multi_assign", False),
            "inject_publication_scope_into_global": editorial_config.get(
                "inject_publication_scope_into_global", True
            ),
            "assignment_batch_size": editorial_config.get("assignment_batch_size", 20),
        },
        "search": search_config,
        "channels": ["wecom_main"],
        "schedule": schedule,
    }

    tasks = {"tasks": {"daily_brief": task_def}}
    save_tasks(tasks, bot_dir)
    logger.info("tasks.json generated.")
    logger.info("Migration complete.")
