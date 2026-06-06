import os
from pathlib import Path

from .ids import require_safe_id


def default_bot_dir() -> str:
    env_dir = os.getenv("MARKETING_BOT_DIR")
    if env_dir:
        return env_dir
    if os.path.isdir("/root/marketing_bot"):
        return "/root/marketing_bot"
    return os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


def logs_dir(bot_dir: str | None = None) -> str:
    bot_dir = bot_dir or default_bot_dir()
    return os.getenv("LOGS_DIR", os.path.join(bot_dir, "logs"))


def data_dir(bot_dir: str | None = None) -> str:
    bot_dir = bot_dir or default_bot_dir()
    return os.getenv("DATA_DIR", os.path.join(bot_dir, "data"))


def config_file_path(bot_dir: str | None = None) -> str:
    bot_dir = bot_dir or default_bot_dir()
    return os.getenv("CONFIG_FILE", os.path.join(bot_dir, "config.json"))


def config_content_file_path(bot_dir: str | None = None) -> str:
    bot_dir = bot_dir or default_bot_dir()
    return os.getenv("CONFIG_CONTENT_FILE", os.path.join(bot_dir, "config.content.json"))


def config_secrets_file_path(bot_dir: str | None = None) -> str:
    bot_dir = bot_dir or default_bot_dir()
    return os.getenv("CONFIG_SECRETS_FILE", os.path.join(bot_dir, "config.secrets.json"))


def bot_log_file_path(bot_dir: str | None = None) -> str:
    bot_dir = bot_dir or default_bot_dir()
    return os.getenv("BOT_LOG_FILE", os.path.join(logs_dir(bot_dir), "bot.log"))


def cron_log_file_path(bot_dir: str | None = None) -> str:
    bot_dir = bot_dir or default_bot_dir()
    return os.getenv("LOG_FILE", os.path.join(logs_dir(bot_dir), "cron.log"))


def feed_health_cache_file_path(bot_dir: str | None = None) -> str:
    bot_dir = bot_dir or default_bot_dir()
    return os.getenv("FEED_HEALTH_CACHE_FILE", os.path.join(data_dir(bot_dir), "feed_health_cache.json"))


def prompt_debug_history_file_path(bot_dir: str | None = None) -> str:
    bot_dir = bot_dir or default_bot_dir()
    return os.getenv("PROMPT_DEBUG_HISTORY_FILE", os.path.join(data_dir(bot_dir), "prompt_debug_history.json"))


def channels_file_path(bot_dir: str | None = None) -> str:
    bot_dir = bot_dir or default_bot_dir()
    return os.getenv("CHANNELS_FILE", os.path.join(bot_dir, "channels.json"))


def tasks_file_path(bot_dir: str | None = None) -> str:
    bot_dir = bot_dir or default_bot_dir()
    return os.getenv("TASKS_FILE", os.path.join(bot_dir, "tasks.json"))


def task_runs_file_path(bot_dir: str | None = None) -> str:
    bot_dir = bot_dir or default_bot_dir()
    return os.getenv("TASK_RUNS_FILE", os.path.join(data_dir(bot_dir), "task_runs.jsonl"))


def task_health_cache_file_path(task_id: str, bot_dir: str | None = None) -> str:
    bot_dir = bot_dir or default_bot_dir()
    override = os.getenv("TASK_HEALTH_CACHE_FILE")
    if override:
        return override
    safe_task_id = require_safe_id(task_id, label="task_id")
    base_dir = Path(data_dir(bot_dir)).resolve() / "task_health"
    target = (base_dir / f"{safe_task_id}.json").resolve()
    if base_dir.resolve() not in target.parents:
        raise ValueError("Task health path escaped task_health directory.")
    return str(target)


def task_state_file_path(task_id: str, bot_dir: str | None = None) -> str:
    bot_dir = bot_dir or default_bot_dir()
    override = os.getenv("TASK_STATE_FILE")
    if override:
        return override
    safe_task_id = require_safe_id(task_id, label="task_id")
    base_dir = Path(data_dir(bot_dir)).resolve() / "task_state"
    target = (base_dir / f"{safe_task_id}.json").resolve()
    if base_dir.resolve() not in target.parents:
        raise ValueError("Task state path escaped task_state directory.")
    return str(target)
