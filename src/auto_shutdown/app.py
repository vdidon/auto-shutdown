"""Assemblage des trois composants et de leurs threads.

Répartition des rôles :

- thread principal : boucle tkinter (`Ui.run`) ;
- thread `tray` : fenêtre Windows, menu et notifications d'alimentation ;
- thread `scheduler` : décompte et déclenchement.

Tout ce qui touche à tkinter est réacheminé vers le thread principal par
`Ui.call`. Les deux autres composants sont conçus pour être sollicités depuis
n'importe quel thread.
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import threading

from . import __version__, winapi
from . import log as log_module
from . import tray as tray_module
from .config import Config
from .power import Action
from .scheduler import CancelReason, Scheduler, Snapshot, State
from .tray import Tray, TrayCallbacks
from .ui import Ui, UiCallbacks, format_duration

log = logging.getLogger(__name__)

MUTEX_NAME = "Local\\AutoShutdownSingleInstance"


def _enable_dpi_awareness() -> None:
    """Rend l'interface nette sur les écrans à forte densité.

    Sans cela, Windows étire l'interface et le texte devient flou. L'échec de
    l'appel est sans gravité : seule l'esthétique en pâtit.
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            log.debug("Impossible d'activer la prise en charge du DPI")


class Application:
    """Cycle de vie complet de l'application."""

    def __init__(self, config: Config, *, open_config: bool = True) -> None:
        self._config = config
        self._open_config = open_config
        self._last_tooltip = ""
        self._quitting = False

        self._scheduler = Scheduler(
            quiet_seconds=config.input_quiet_seconds,
            quiet_timeout=config.input_quiet_timeout,
            stall_threshold=config.stall_threshold_seconds,
            on_tick=self._on_tick,
            on_reminder=self._on_reminder,
            on_fired=self._on_fired,
            on_cancelled=self._on_cancelled,
        )

        self._ui = Ui(
            config,
            UiCallbacks(
                on_arm=self._arm,
                on_cancel=self._cancel,
                on_postpone=self._postpone,
                on_quit=self.quit,
                snapshot=self._scheduler.snapshot,
            ),
        )

        self._tray = Tray(
            TrayCallbacks(
                on_configure=lambda: self._ui.call(self._ui.show_config),
                on_cancel=self._cancel,
                on_postpone=self._postpone,
                on_open_log=self._open_log,
                on_quit=self.quit,
                on_suspend=self._scheduler.on_suspend,
                on_resume=self._scheduler.on_resume,
                query_state=self._query_state,
            )
        )
        self._tray_thread = threading.Thread(target=self._tray.run, name="tray", daemon=True)

    # -- cycle de vie ------------------------------------------------------

    def run(self) -> int:
        self._scheduler.start()
        self._tray_thread.start()
        if not self._tray.wait_ready():
            log.error("La zone de notification n'a pas répondu ; arrêt")
            return 1

        self._refresh_tray(self._scheduler.snapshot())
        if self._open_config:
            # Planifié plutôt qu'appelé : la fenêtre doit naître dans la boucle
            # tkinter, que `run` démarre juste après.
            self._ui.call(self._ui.show_config)
        log.info("Application démarrée")
        self._ui.run()
        log.info("Application arrêtée")
        return 0

    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self._scheduler.stop()
        self._tray.shutdown()
        self._ui.quit()

    # -- commandes ---------------------------------------------------------

    def _arm(self, action: Action, delay_minutes: int, reminder_minutes: int) -> None:
        snapshot = self._scheduler.arm(action, delay_minutes, reminder_minutes)
        self._refresh_tray(snapshot)
        self._tray.notify(
            "Tâche programmée",
            f"{action.value} dans {format_duration(snapshot.remaining)}.",
        )

    def _cancel(self) -> None:
        if not self._scheduler.cancel(CancelReason.USER):
            return
        self._refresh_tray(self._scheduler.snapshot())

    def _postpone(self, minutes: int) -> None:
        snapshot = self._scheduler.postpone(minutes)
        if snapshot is None:
            return
        self._refresh_tray(snapshot)
        self._tray.notify("Tâche reportée", f"Nouvelle échéance dans {minutes} minutes.")

    def _open_log(self) -> None:
        path = log_module.log_path()
        try:
            os.startfile(path)
        except OSError:
            log.exception("Impossible d'ouvrir le journal %s", path)

    def _query_state(self) -> tuple[bool, str]:
        snapshot = self._scheduler.snapshot()
        if snapshot.armed and snapshot.action is not None:
            return True, f"{snapshot.action.value} dans {format_duration(snapshot.remaining)}"
        return False, "Aucune tâche programmée"

    # -- réactions à l'ordonnanceur ----------------------------------------

    def _on_tick(self, snapshot: Snapshot) -> None:
        self._refresh_tray(snapshot)
        self._ui.call(self._ui.refresh)

    def _on_reminder(self, snapshot: Snapshot) -> None:
        self._ui.call(self._ui.show_reminder, snapshot)
        self._tray.notify(
            "Rappel",
            f"{snapshot.action.value if snapshot.action else 'Action'} dans "
            f"{format_duration(snapshot.remaining)}.",
            warning=True,
        )

    def _on_fired(self, action: Action) -> None:
        self._ui.call(self._ui.close_reminder)
        self._refresh_tray(self._scheduler.snapshot())
        log.info("Déclenchement de %s", action.name)

    def _on_cancelled(self, reason: CancelReason) -> None:
        self._ui.call(self._ui.close_reminder)
        self._ui.call(self._ui.refresh)
        self._refresh_tray(self._scheduler.snapshot())
        # Rendre l'annulation visible : c'est précisément ce que l'utilisateur
        # doit pouvoir constater, plutôt que subir un ré-endormissement
        # inexpliqué.
        messages = {
            CancelReason.RESUME: (
                "La machine est sortie de veille : la tâche programmée a été "
                "annulée pour éviter un nouveau cycle de veille."
            ),
            CancelReason.STALL: (
                "Le décompte a été interrompu, signe que la machine a été "
                "suspendue. La tâche a été annulée par sécurité."
            ),
        }
        message = messages.get(reason)
        if message is not None:
            self._tray.notify("Tâche annulée", message, warning=True)

    # -- présentation ------------------------------------------------------

    def _refresh_tray(self, snapshot: Snapshot) -> None:
        if snapshot.state is State.REMINDING:
            color = tray_module.COLOR_REMINDING
        elif snapshot.armed:
            color = tray_module.COLOR_ARMED
        else:
            color = tray_module.COLOR_IDLE

        if snapshot.armed and snapshot.action is not None:
            tooltip = (
                f"Auto Shutdown\n{snapshot.action.value} dans {format_duration(snapshot.remaining)}"
            )
        else:
            tooltip = "Auto Shutdown\nAucune tâche programmée"

        # L'ordonnanceur bat quatre fois par seconde ; l'infobulle ne change
        # qu'à la seconde. Filtrer évite autant d'allers-retours vers le shell.
        if tooltip == self._last_tooltip:
            return
        self._last_tooltip = tooltip
        self._tray.set_state(color, tooltip)


def main(argv: list[str] | None = None) -> int:
    """Point d'entrée."""
    parser = argparse.ArgumentParser(
        prog="auto-shutdown",
        description="Programme une mise en veille, un arrêt ou un verrouillage différé.",
    )
    parser.add_argument("--version", action="version", version=f"auto-shutdown {__version__}")
    parser.add_argument(
        "--verbose", action="store_true", help="journalisation détaillée sur la console"
    )
    parser.add_argument(
        "--minimized",
        action="store_true",
        help="démarre dans la zone de notification, sans ouvrir la fenêtre de configuration "
        "(destiné au lancement automatique à l'ouverture de session)",
    )
    args = parser.parse_args(argv)

    path = log_module.setup(verbose=args.verbose)
    # Première ligne de chaque session : sans elle, un journal remonté par un
    # utilisateur ne dit pas quelle version l'a produit.
    log.info("auto-shutdown %s — journal : %s", __version__, path)

    mutex = winapi.acquire_single_instance_mutex(MUTEX_NAME)
    if mutex is None:
        log.error("Une autre instance est déjà en cours d'exécution")
        return 2

    _enable_dpi_awareness()
    winapi.enable_shutdown_privilege()

    config = Config.load()
    try:
        return Application(config, open_config=not args.minimized).run()
    finally:
        winapi.kernel32.CloseHandle(mutex)
