"""Actions d'alimentation et précautions qui les entourent."""

from __future__ import annotations

import ctypes
import logging
import time
from enum import Enum

from . import winapi

log = logging.getLogger(__name__)


class Action(Enum):
    """Action exécutée à l'échéance.

    La valeur est le libellé affiché dans l'interface.
    """

    HIBERNATE = "Mettre en veille prolongée"
    SLEEP = "Mettre en veille"
    SHUTDOWN = "Arrêter"
    RESTART = "Redémarrer"
    LOGOFF = "Fermer la session"
    LOCK = "Verrouiller l'écran"

    @property
    def suspends(self) -> bool:
        """Vrai si l'action suspend la machine.

        Ces actions rendent la main au retour de veille, contrairement à un
        arrêt ou un redémarrage — ce qui impose de neutraliser toute tâche
        encore armée à la reprise.
        """
        return self in (Action.HIBERNATE, Action.SLEEP)

    @property
    def is_terminal(self) -> bool:
        """Vrai si l'action met fin au processus (arrêt, redémarrage, session)."""
        return self in (Action.SHUTDOWN, Action.RESTART, Action.LOGOFF)

    @classmethod
    def parse(cls, name: str) -> Action:
        """Convertit un nom stocké en configuration, avec repli sûr."""
        try:
            return cls[name]
        except KeyError:
            log.warning("Action inconnue %r, repli sur HIBERNATE", name)
            return cls.HIBERNATE


def wait_for_input_quiet(quiet_seconds: float, timeout: float) -> bool:
    """Attend une période sans entrée clavier/souris avant de suspendre.

    Sur cette machine, `powercfg /devicequery wake_armed` ne renvoie que la
    souris : un appel à `SetSuspendState` émis alors qu'un mouvement est encore
    en cours de traitement fait ressortir le système de veille dans la seconde.
    Attendre le calme supprime ce rebond.

    Renvoie `True` si le calme a été obtenu, `False` si le plafond d'attente a
    été atteint — auquel cas l'appelant exécute quand même l'action, puisque
    l'utilisateur a déjà eu l'occasion de l'annuler via le rappel.
    """
    if quiet_seconds <= 0:
        return True
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        idle = winapi.idle_seconds()
        if idle >= quiet_seconds:
            return True
        # Dormir juste ce qu'il manque, borné pour rester réactif.
        time.sleep(min(quiet_seconds - idle, 1.0))
    log.warning(
        "Entrée toujours active après %.0f s d'attente : exécution malgré tout",
        timeout,
    )
    return False


def execute(action: Action, *, quiet_seconds: float = 0.0, quiet_timeout: float = 30.0) -> None:
    """Exécute l'action demandée.

    Pour une mise en veille, l'appel à `SetSuspendState` est bloquant : il ne
    rend la main qu'au réveil de la machine.
    """
    if action.suspends:
        wait_for_input_quiet(quiet_seconds, quiet_timeout)

    log.info("Exécution de l'action %s", action.name)

    if action is Action.LOCK:
        if not winapi.user32.LockWorkStation():
            _raise_last_error("LockWorkStation")
        return

    if action.suspends:
        hibernate = action is Action.HIBERNATE
        # Troisième paramètre (bWakeupEventsDisabled) laissé à False : il est
        # ignoré par Windows depuis Vista, le passer à True n'empêche rien.
        if not winapi.powrprof.SetSuspendState(hibernate, False, False):
            _raise_last_error("SetSuspendState")
        log.info("Retour de veille après %s", action.name)
        return

    flags = {
        Action.SHUTDOWN: winapi.EWX_SHUTDOWN,
        Action.RESTART: winapi.EWX_REBOOT,
        Action.LOGOFF: winapi.EWX_LOGOFF,
    }[action]
    reason = (
        winapi.SHTDN_REASON_MAJOR_OTHER
        | winapi.SHTDN_REASON_MINOR_OTHER
        | winapi.SHTDN_REASON_FLAG_PLANNED
    )
    if not winapi.user32.ExitWindowsEx(flags | winapi.EWX_FORCEIFHUNG, reason):
        _raise_last_error("ExitWindowsEx")


def _raise_last_error(call: str) -> None:
    code = ctypes.get_last_error()
    raise OSError(code, f"{call} a échoué (code {code})")
