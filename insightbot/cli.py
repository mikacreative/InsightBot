from .config import load_runtime_config
from .logging_setup import build_logger
from .paths import bot_log_file_path, default_bot_dir


def main() -> None:
    bot_dir = default_bot_dir()
    log_path = bot_log_file_path(bot_dir)

    config = load_runtime_config(bot_dir)
    logger = build_logger("MIABot", log_path)

    editorial_config = (config.get("ai", {}) or {}).get("editorial_pipeline", {})
    if editorial_config.get("enabled", False):
        from .editorial_pipeline import run_editorial_pipeline
        logger.info("🚀 走 Editorial Pipeline（新流程）")
        run_editorial_pipeline(config=config, logger=logger)
    else:
        from .smart_brief_runner import run_task
        logger.info("🚀 走传统 Pipeline（老流程）")
        run_task(config=config, logger=logger)


if __name__ == "__main__":
    main()
