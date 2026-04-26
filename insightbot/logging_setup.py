import logging
import os
from logging.handlers import TimedRotatingFileHandler


_MANAGED_HANDLER_ATTR = "_insightbot_managed_handler"


def _is_managed_handler(handler: logging.Handler) -> bool:
    return bool(getattr(handler, _MANAGED_HANDLER_ATTR, False))


def build_logger(name: str, log_file: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if any(_is_managed_handler(handler) for handler in logger.handlers):
        return logger

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(name)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    log_dir = os.path.dirname(os.path.abspath(log_file))
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    file_handler = TimedRotatingFileHandler(
        log_file, when="midnight", interval=1, backupCount=30, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    setattr(file_handler, _MANAGED_HANDLER_ATTR, True)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    setattr(console_handler, _MANAGED_HANDLER_ATTR, True)
    logger.addHandler(console_handler)
    logger.propagate = False

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    if not any(_is_managed_handler(handler) for handler in root_logger.handlers):
        root_file_handler = TimedRotatingFileHandler(
            log_file, when="midnight", interval=1, backupCount=30, encoding="utf-8"
        )
        root_file_handler.setFormatter(formatter)
        setattr(root_file_handler, _MANAGED_HANDLER_ATTR, True)
        root_logger.addHandler(root_file_handler)

        root_console_handler = logging.StreamHandler()
        root_console_handler.setFormatter(formatter)
        setattr(root_console_handler, _MANAGED_HANDLER_ATTR, True)
        root_logger.addHandler(root_console_handler)

    return logger
