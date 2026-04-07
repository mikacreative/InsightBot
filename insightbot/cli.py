from .config import load_runtime_config
from .logging_setup import build_logger
from .paths import bot_log_file_path, default_bot_dir
from .smart_brief_runner import run_task


def main() -> None:
    bot_dir = default_bot_dir()
    log_path = bot_log_file_path(bot_dir)

    config = load_runtime_config(bot_dir)
    logger = build_logger("MIABot", log_path)
    run_task(config=config, logger=logger)


if __name__ == "__main__":
    main()
