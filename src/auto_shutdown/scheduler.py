"""Ordonnanceur d'une tâche unique, conçu pour ne jamais se déclencher deux fois.

Quatre règles portent l'essentiel de la fiabilité :

1. **Base de temps monotone.** L'échéance est un instant `time.monotonic()`, pas
   une date. Un changement d'heure système, un fuseau ou un décalage NTP ne
   peuvent donc pas rendre l'échéance subitement « dépassée ».
2. **Désarmement avant exécution.** La tâche quitte l'état armé *avant* que
   l'action ne soit lancée. Il n'existe aucun instant où une tâche déjà partie
   reste armée.
3. **Annulation à la reprise de veille.** Toute reprise annule une tâche encore
   armée. C'est ce qui interdit la boucle « réveil → ré-endormissement
   immédiat » : après une reprise, seul l'utilisateur peut réarmer.
4. **Détection d'interruption du décompte.** Si deux passages successifs sont
   séparés par bien plus que la période de scrutation, c'est que le processus a
   été gelé — machine suspendue. Une échéance franchie pendant ce gel est
   annulée au lieu d'être exécutée.

La règle 4 est le filet de la règle 3. En veille moderne (`S0 Low Power Idle`),
l'horloge monotone continue de progresser pendant la veille : une échéance peut
donc être franchie sans que personne ne soit là pour la voir. Si la notification
de reprise venait à manquer, l'action partirait dans la seconde suivant le
réveil — exactement le défaut que ce projet corrige. La règle 4 ne dépend
d'aucune notification Windows.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto

from .power import Action, execute

log = logging.getLogger(__name__)

#: Période de scrutation. Assez fine pour un compte à rebours à la seconde,
#: assez large pour un coût processeur nul.
TICK_SECONDS = 0.25

#: Au-delà de cet écart entre deux passages, le décompte est considéré comme
#: ayant été interrompu. Large devant `TICK_SECONDS` et devant tout à-coup
#: d'ordonnancement du système, court devant n'importe quelle veille réelle.
STALL_THRESHOLD_SECONDS = 60.0


class State(Enum):
    IDLE = auto()
    ARMED = auto()
    REMINDING = auto()


class CancelReason(Enum):
    USER = "annulée par l'utilisateur"
    RESUME = "annulée automatiquement au retour de veille"
    STALL = "annulée : le décompte a été interrompu"
    SHUTDOWN = "arrêt de l'application"


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Vue instantanée et immuable de l'état, sûre à lire depuis un autre thread."""

    state: State
    action: Action | None
    remaining: float
    reminder_active: bool

    @property
    def armed(self) -> bool:
        return self.state in (State.ARMED, State.REMINDING)


class Scheduler:
    """Gère une tâche unique et son compte à rebours.

    Les fonctions de rappel sont invoquées depuis le thread interne : à charge
    de l'appelant de les réacheminer vers son thread d'interface.
    """

    def __init__(  # noqa: PLR0913  (réglages et rappels, tous nommés et facultatifs)
        self,
        *,
        quiet_seconds: float = 3.0,
        quiet_timeout: float = 30.0,
        stall_threshold: float = STALL_THRESHOLD_SECONDS,
        on_tick: Callable[[Snapshot], None] | None = None,
        on_reminder: Callable[[Snapshot], None] | None = None,
        on_fired: Callable[[Action], None] | None = None,
        on_cancelled: Callable[[CancelReason], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        runner: Callable[[Action], None] | None = None,
    ) -> None:
        # `clock` et `runner` sont injectables pour que la logique d'échéance
        # soit vérifiable sans attendre le temps réel ni endormir la machine.
        self._clock = clock
        self._runner = runner or self._default_runner
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()

        self._state = State.IDLE
        self._action: Action | None = None
        self._deadline: float | None = None
        self._reminder_at: float | None = None
        self._last_poll: float | None = None

        self._quiet_seconds = quiet_seconds
        self._quiet_timeout = quiet_timeout
        self._stall_threshold = stall_threshold

        self._on_tick = on_tick
        self._on_reminder = on_reminder
        self._on_fired = on_fired
        self._on_cancelled = on_cancelled

        self._thread = threading.Thread(target=self._run, name="scheduler", daemon=True)

    # -- cycle de vie ------------------------------------------------------

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        with self._lock:
            was_armed = self._state in (State.ARMED, State.REMINDING)
            self._reset()
        self._stop.set()
        self._wake.set()
        if was_armed:
            self._notify(self._on_cancelled, CancelReason.SHUTDOWN)

    # -- commandes ---------------------------------------------------------

    def arm(self, action: Action, delay_minutes: int, reminder_minutes: int = 0) -> Snapshot:
        """Arme la tâche pour dans `delay_minutes` minutes."""
        now = self._clock()
        delay = max(0, int(delay_minutes)) * 60.0
        with self._lock:
            self._action = action
            self._deadline = now + delay
            reminder = max(0, int(reminder_minutes)) * 60.0
            # Le rappel n'a de sens que s'il tombe dans le futur et avant l'échéance.
            self._reminder_at = now + delay - reminder if 0 < reminder < delay else None
            self._state = State.ARMED
            # Repartir de l'instant présent : le temps écoulé avant l'armement
            # ne doit pas être compté comme une interruption du décompte.
            self._last_poll = now
            snapshot = self._snapshot_locked(now)
        log.info(
            "Tâche armée : %s dans %d min (rappel %s)",
            action.name,
            delay_minutes,
            f"{reminder_minutes} min avant" if self._reminder_at else "désactivé",
        )
        self._wake.set()
        return snapshot

    def cancel(self, reason: CancelReason = CancelReason.USER) -> bool:
        """Désarme la tâche. Renvoie `True` si une tâche était bien armée."""
        with self._lock:
            if self._state not in (State.ARMED, State.REMINDING):
                return False
            action = self._action
            self._reset()
        log.info("Tâche %s annulée (%s)", action.name if action else "?", reason.value)
        self._wake.set()
        self._notify(self._on_cancelled, reason)
        return True

    def postpone(self, minutes: int) -> Snapshot | None:
        """Repousse l'échéance de `minutes` à partir de maintenant.

        Le rappel est reconduit avec la même avance, sauf si celle-ci ne tient
        plus dans le nouveau délai.
        """
        with self._lock:
            if self._state not in (State.ARMED, State.REMINDING) or self._action is None:
                return None
            action = self._action
            previous_reminder = (
                int((self._deadline - self._reminder_at) / 60)
                if self._deadline is not None and self._reminder_at is not None
                else 0
            )
        reminder = previous_reminder if previous_reminder < minutes else 0
        return self.arm(action, minutes, reminder)

    # -- notifications d'alimentation --------------------------------------

    def on_suspend(self) -> None:
        """Le système part en veille (`PBT_APMSUSPEND`)."""
        log.info("Notification système : entrée en veille")

    def on_resume(self) -> None:
        """Le système sort de veille (`PBT_APMRESUME*`).

        Point central du correctif. Une tâche encore armée est annulée plutôt
        que laissée à courir : sans cela, une échéance perçue comme dépassée se
        déclenche dans les secondes qui suivent la reprise et renvoie la machine
        en veille.

        Windows émet souvent `PBT_APMRESUMESUSPEND` puis
        `PBT_APMRESUMEAUTOMATIC` pour une même reprise : le traitement est donc
        idempotent.
        """
        with self._lock:
            armed = self._state in (State.ARMED, State.REMINDING)
            if armed:
                self._reset()
            # Le décompte reprend d'ici : l'intervalle passé en veille ne doit
            # pas être compté deux fois par la détection d'interruption.
            self._last_poll = self._clock()
        log.info(
            "Notification système : retour de veille%s",
            " — tâche armée annulée" if armed else "",
        )
        self._wake.set()
        if armed:
            self._notify(self._on_cancelled, CancelReason.RESUME)

    # -- lecture -----------------------------------------------------------

    def snapshot(self) -> Snapshot:
        with self._lock:
            return self._snapshot_locked(self._clock())

    def _snapshot_locked(self, now: float) -> Snapshot:
        remaining = max(0.0, self._deadline - now) if self._deadline is not None else 0.0
        return Snapshot(
            state=self._state,
            action=self._action,
            remaining=remaining,
            reminder_active=self._state is State.REMINDING,
        )

    # -- boucle interne ----------------------------------------------------

    def _reset(self) -> None:
        """Remet l'état au repos. À n'appeler qu'en tenant le verrou."""
        self._state = State.IDLE
        self._action = None
        self._deadline = None
        self._reminder_at = None

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(TICK_SECONDS)
            self._wake.clear()
            if self._stop.is_set():
                return
            self.poll()

    def poll(self) -> None:
        """Fait avancer l'ordonnanceur d'un pas.

        Appelée par la boucle interne ; publique pour permettre de piloter
        l'ordonnanceur avec une horloge simulée.
        """
        now = self._clock()
        due_action: Action | None = None
        reminder_snapshot: Snapshot | None = None
        stalled = False

        with self._lock:
            previous_poll = self._last_poll
            self._last_poll = now

            if self._state not in (State.ARMED, State.REMINDING) or self._deadline is None:
                return

            # Règle 4 : un trou dans le décompte signale une machine suspendue.
            # L'échéance franchie pendant ce trou n'est pas jouée.
            if previous_poll is not None and now - previous_poll > self._stall_threshold:
                stalled = True
                self._reset()
            elif now >= self._deadline:
                # Règle 2 : on désarme d'abord, on exécute ensuite. Si l'action
                # rend la main (retour de veille), il ne reste rien d'armé.
                due_action = self._action
                self._reset()
            elif (
                self._state is State.ARMED
                and self._reminder_at is not None
                and now >= self._reminder_at
            ):
                self._state = State.REMINDING
                reminder_snapshot = self._snapshot_locked(now)

            tick_snapshot = self._snapshot_locked(now)

        if stalled:
            log.warning(
                "Décompte interrompu pendant %.0f s : tâche annulée par sécurité",
                now - (previous_poll or now),
            )
            self._notify(self._on_cancelled, CancelReason.STALL)
            return
        if due_action is not None:
            self._fire(due_action)
            return
        if reminder_snapshot is not None:
            log.info(
                "Rappel : %s dans %.0f s",
                reminder_snapshot.action.name if reminder_snapshot.action else "?",
                reminder_snapshot.remaining,
            )
            self._notify(self._on_reminder, reminder_snapshot)
        self._notify(self._on_tick, tick_snapshot)

    def _fire(self, action: Action) -> None:
        self._notify(self._on_fired, action)
        self._runner(action)

    def _default_runner(self, action: Action) -> None:
        # `execute` bloque jusqu'au réveil pour une mise en veille : il lui faut
        # son propre thread, sinon la boucle ne verrait plus passer ni les
        # annulations ni les notifications d'alimentation.
        threading.Thread(
            target=self._execute_guarded, args=(action,), name="power-action", daemon=True
        ).start()

    def _execute_guarded(self, action: Action) -> None:
        try:
            execute(
                action,
                quiet_seconds=self._quiet_seconds,
                quiet_timeout=self._quiet_timeout,
            )
        except OSError:
            log.exception("Échec de l'action %s", action.name)

    def _notify[T](self, callback: Callable[[T], None] | None, value: T) -> None:
        """Invoque une fonction de rappel sans jamais laisser remonter d'exception.

        Une erreur d'interface ne doit pas tuer le thread d'ordonnancement, au
        risque de laisser une tâche armée que plus rien ne surveille.
        """
        if callback is None:
            return
        try:
            callback(value)
        except Exception:
            log.exception("Erreur dans une fonction de rappel de l'ordonnanceur")
