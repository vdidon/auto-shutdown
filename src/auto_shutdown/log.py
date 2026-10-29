"""Logging to a rotating file.

Every power transition is recorded there with its timestamp. This is what makes
it possible, after the fact, to answer the question that utilities of this kind
usually leave unanswered: *what put the machine to sleep or woke it up, and at
what time?*
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import data_dir

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)-24s %(message)s"
MAX_BYTES = 512 * 1024
BACKUP_COUNT = 3


def log_path() -> Path:
    return data_dir() / "auto-shutdown.log"


def setup(*, verbose: bool = False) -> Path:
    """Set up file and console logging. Return the log file path."""
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    # Avoid stacking handlers if `setup` is called again (tests, relaunch).
    for handler in list(root.handlers):
        root.removeHandler(handler)

    file_handler = RotatingFileHandler(
        path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(file_handler)

    if verbose:
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(console)

    return path
