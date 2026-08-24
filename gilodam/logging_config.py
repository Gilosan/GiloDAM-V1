from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(log_directory: Path) -> logging.Logger:
    logger = logging.getLogger("gilodam")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    log_directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_directory / "gilodam.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    return logger

