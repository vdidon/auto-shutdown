"""Configuration persistée dans le profil de l'utilisateur."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Final

APP_NAME = "auto-shutdown"

#: Icône appliquée aux fenêtres, et à l'exécutable lors de la construction.
ICON_FILE = "auto-shutdown.ico"

#: Durées de report proposées, en minutes. Source unique : la fenêtre de rappel
#: et le menu de la zone de notification s'en servent toutes deux.
POSTPONE_CHOICES: Final = (5, 10, 15, 30)

#: Bornes du délai, en minutes. Un délai nul déclencherait l'action à l'instant
#: même où la tâche est armée, sans laisser le temps d'annuler.
MIN_DELAY_MINUTES = 1
MAX_DELAY_MINUTES = 24 * 60 * 7


def config_dir() -> Path:
    """Répertoire de configuration (`%APPDATA%\\auto-shutdown`)."""
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / APP_NAME


def data_dir() -> Path:
    """Répertoire des données volatiles, journal compris."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_NAME


def asset_path(name: str) -> Path:
    """Chemin d'une ressource, qu'on tourne depuis les sources ou un exécutable.

    En mode `--onefile`, PyInstaller extrait les ressources embarquées dans un
    répertoire temporaire dont le chemin est publié par `sys._MEIPASS`.
    """
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled is not None:
        return Path(bundled) / "assets" / name
    return Path(__file__).resolve().parents[2] / "assets" / name


@dataclass(slots=True)
class Config:
    """Réglages de l'application.

    `action` est le nom d'un membre de `power.Action`. Il est stocké sous forme
    de chaîne pour que le fichier reste lisible et modifiable à la main.
    """

    action: str = "HIBERNATE"
    delay_minutes: int = 30

    #: Rappel affiché avant l'échéance, avec possibilité d'annuler ou de reporter.
    reminder_enabled: bool = True
    reminder_minutes: int = 5

    #: Durée sans entrée clavier/souris exigée avant de suspendre la machine.
    #: Sur un système où la souris est armée pour le réveil, suspendre pendant
    #: qu'un mouvement est encore en cours provoque un réveil immédiat.
    input_quiet_seconds: float = 3.0

    #: Plafond d'attente du calme d'entrée : au-delà, l'action est exécutée
    #: malgré tout, l'utilisateur ayant déjà eu le rappel pour annuler.
    input_quiet_timeout: float = 30.0

    #: Écart entre deux passages du décompte au-delà duquel celui-ci est jugé
    #: interrompu — signe que la machine a été suspendue. Une échéance franchie
    #: pendant cette interruption est annulée plutôt qu'exécutée.
    stall_threshold_seconds: float = 60.0

    def path(self) -> Path:
        return config_dir() / "config.json"

    @classmethod
    def load(cls) -> Config:
        """Relit la configuration ; retombe sur les valeurs par défaut si besoin.

        Un fichier corrompu ou partiel ne doit jamais empêcher le démarrage :
        les clés inconnues sont ignorées et les manquantes gardent leur défaut.
        """
        path = config_dir() / "config.json"
        if not path.is_file():
            return cls()
        try:
            raw: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self) -> None:
        path = self.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Écriture puis remplacement atomique : une coupure ne laisse jamais
        # un fichier de configuration tronqué.
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        tmp.replace(path)

    def clamped_delay(self) -> int:
        """Délai ramené dans les bornes acceptables."""
        return max(MIN_DELAY_MINUTES, min(MAX_DELAY_MINUTES, int(self.delay_minutes)))

    def effective_reminder_minutes(self) -> int:
        """Avance du rappel, jamais supérieure ou égale au délai lui-même.

        Un rappel programmé au-delà de l'échéance ne se déclencherait pas ;
        un rappel exactement à l'échéance ne laisserait aucun temps de réaction.
        """
        if not self.reminder_enabled:
            return 0
        return max(0, min(int(self.reminder_minutes), self.clamped_delay() - 1))
