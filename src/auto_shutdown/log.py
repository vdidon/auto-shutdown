"""Journalisation vers un fichier tournant.

Chaque transition d'alimentation y est tracée avec son horodatage. C'est ce qui
permet, après coup, de répondre à la question que les utilitaires de ce genre
laissent en général sans réponse : *qu'est-ce qui a endormi ou réveillé la
machine, et à quelle heure ?*
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
    """Installe la journalisation fichier et console. Renvoie le chemin du journal."""
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    # Éviter d'empiler les gestionnaires si `setup` est rappelé (tests, relance).
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
