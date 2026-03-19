import os


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


def config_file_path(bot_dir: str | None = None) -> str:
    bot_dir = bot_dir or default_bot_dir()
    return os.getenv("CONFIG_FILE", os.path.join(bot_dir, "config.json"))


def bot_log_file_path(bot_dir: str | None = None) -> str:
    bot_dir = bot_dir or default_bot_dir()
    return os.getenv("BOT_LOG_FILE", os.path.join(logs_dir(bot_dir), "bot.log"))


def cron_log_file_path(bot_dir: str | None = None) -> str:
    bot_dir = bot_dir or default_bot_dir()
    return os.getenv("LOG_FILE", os.path.join(logs_dir(bot_dir), "cron.log"))

