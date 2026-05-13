import logging


def test_build_logger_routes_child_loggers_to_same_file(tmp_path):
    from insightbot.logging_setup import build_logger

    log_file = tmp_path / "bot.log"
    logger = build_logger("InsightBotTest", str(log_file))
    child_logger = logging.getLogger("Scheduler")

    logger.info("top level")
    child_logger.info("child level")

    for handler in logging.getLogger().handlers + logger.handlers:
        handler.flush()

    text = log_file.read_text(encoding="utf-8")
    assert "[InsightBotTest] top level" in text
    assert "[Scheduler] child level" in text


def test_build_logger_is_idempotent(tmp_path):
    from insightbot.logging_setup import build_logger

    log_file = tmp_path / "bot.log"
    first = build_logger("InsightBotIdempotent", str(log_file))
    first_handler_count = len(first.handlers)
    root_handler_count = len(logging.getLogger().handlers)

    second = build_logger("InsightBotIdempotent", str(log_file))

    assert second is first
    assert len(second.handlers) == first_handler_count
    assert len(logging.getLogger().handlers) == root_handler_count
