"""Application logging helpers."""

from __future__ import annotations

import logging
from pathlib import Path


LOGGER_NAME = "pdf_redactor"


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def configure_logging(log_folder: Path | None = None) -> logging.Logger:
    """Configure console and optional file logging for the app."""

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_folder is not None:
        log_folder.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_folder / "pdf_redactor.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
