"""Vérifications de l'ordonnanceur, horloge et exécuteur simulés.

Les scénarios reproduisent les défaillances observées dans le journal Windows
de la machine ayant motivé ce projet : une tâche programmée y était rejouée
deux secondes après chaque retour de veille, renvoyant aussitôt le poste en
veille prolongée.

Le temps avance par `run_for`, qui rejoue la boucle réelle à petits pas. Faire
bondir l'horloge entre deux passages simulerait une machine suspendue et
déclencherait la détection d'interruption : c'est justement ce que `run_for`
évite, et ce que les tests dédiés provoquent délibérément.
"""

from __future__ import annotations

import pytest

from auto_shutdown.config import POSTPONE_CHOICES
from auto_shutdown.power import Action
from auto_shutdown.scheduler import CancelReason, Scheduler, State


class FakeClock:
    """Horloge monotone pilotée à la main."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Recorder:
    """Exécuteur de remplacement : mémorise au lieu d'endormir la machine."""

    def __init__(self) -> None:
        self.actions: list[Action] = []

    def __call__(self, action: Action) -> None:
        self.actions.append(action)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def runner() -> Recorder:
    return Recorder()


def make_scheduler(clock: FakeClock, runner: Recorder, **kwargs: object) -> Scheduler:
    cancellations: list[CancelReason] = []
    scheduler = Scheduler(
        clock=clock,
        runner=runner,
        on_cancelled=cancellations.append,
        **kwargs,  # type: ignore[arg-type]
    )
    # Exposé pour les assertions ; l'ordonnanceur n'en a pas connaissance.
    scheduler.cancellations = cancellations  # type: ignore[attr-defined]
    return scheduler


def run_for(scheduler: Scheduler, clock: FakeClock, seconds: float, step: float = 10.0) -> None:
    """Fait avancer l'ordonnanceur comme sa boucle interne, à petits pas."""
    elapsed = 0.0
    while elapsed < seconds:
        delta = min(step, seconds - elapsed)
        clock.advance(delta)
        scheduler.poll()
        elapsed += delta


# -- déclenchement nominal ---------------------------------------------------


def test_fires_once_at_deadline(clock: FakeClock, runner: Recorder) -> None:
    scheduler = make_scheduler(clock, runner)
    scheduler.arm(Action.HIBERNATE, 30)

    run_for(scheduler, clock, 29 * 60)
    assert runner.actions == []

    run_for(scheduler, clock, 60)
    assert runner.actions == [Action.HIBERNATE]


def test_does_not_fire_twice(clock: FakeClock, runner: Recorder) -> None:
    """Un désarmement précède l'exécution : aucun second passage possible."""
    scheduler = make_scheduler(clock, runner)
    scheduler.arm(Action.SLEEP, 10)

    run_for(scheduler, clock, 10 * 60)
    for _ in range(20):
        scheduler.poll()

    assert runner.actions == [Action.SLEEP]
    assert not scheduler.snapshot().armed


def test_remaining_counts_down(clock: FakeClock, runner: Recorder) -> None:
    scheduler = make_scheduler(clock, runner)
    scheduler.arm(Action.LOCK, 5)
    assert scheduler.snapshot().remaining == pytest.approx(300.0)

    run_for(scheduler, clock, 120)
    assert scheduler.snapshot().remaining == pytest.approx(180.0)


# -- le correctif : reprise de veille ----------------------------------------


def test_resume_cancels_armed_task(clock: FakeClock, runner: Recorder) -> None:
    """Une reprise de veille désarme la tâche au lieu de la laisser courir."""
    scheduler = make_scheduler(clock, runner)
    scheduler.arm(Action.HIBERNATE, 30)

    run_for(scheduler, clock, 60)
    scheduler.on_resume()

    assert not scheduler.snapshot().armed
    assert scheduler.cancellations == [CancelReason.RESUME]  # type: ignore[attr-defined]

    # Passé l'échéance initiale, plus rien ne se déclenche.
    run_for(scheduler, clock, 60 * 60)
    assert runner.actions == []


def test_no_relaunch_after_hibernation_cycle(clock: FakeClock, runner: Recorder) -> None:
    """Scénario complet observé sur la machine d'origine.

    Une hibernation part à l'heure prévue ; la machine est rallumée le
    lendemain matin. Le défaut consistait à réexécuter l'action dans les
    secondes suivant la reprise. Rien ne doit repartir sans action explicite.
    """
    scheduler = make_scheduler(clock, runner)
    scheduler.arm(Action.HIBERNATE, 30)

    run_for(scheduler, clock, 30 * 60)
    assert runner.actions == [Action.HIBERNATE]

    # `time.monotonic` ne progresse pas pendant l'hibernation : au réveil,
    # l'horloge reprend là où elle s'était arrêtée.
    scheduler.on_resume()
    run_for(scheduler, clock, 50, step=1.0)

    assert runner.actions == [Action.HIBERNATE]
    assert scheduler.snapshot().state is State.IDLE


def test_user_can_arm_right_after_resume(clock: FakeClock, runner: Recorder) -> None:
    """L'annulation automatique ne doit pas empêcher un réarmement volontaire."""
    scheduler = make_scheduler(clock, runner)
    scheduler.arm(Action.HIBERNATE, 30)
    scheduler.on_resume()

    scheduler.arm(Action.SHUTDOWN, 1)
    run_for(scheduler, clock, 60)

    assert runner.actions == [Action.SHUTDOWN]


def test_resume_without_armed_task_is_silent(clock: FakeClock, runner: Recorder) -> None:
    """Les deux événements PBT_* d'une même reprise ne doivent pas doubler."""
    scheduler = make_scheduler(clock, runner)
    scheduler.on_resume()
    scheduler.on_resume()
    assert scheduler.cancellations == []  # type: ignore[attr-defined]


# -- le filet : décompte interrompu ------------------------------------------


def test_stalled_countdown_cancels_instead_of_firing(clock: FakeClock, runner: Recorder) -> None:
    """Sans notification de reprise, un trou dans le décompte protège encore.

    Reproduit la veille moderne : l'horloge monotone progresse pendant la
    veille, l'échéance est donc franchie sans témoin. L'action ne doit pas
    partir au réveil.
    """
    scheduler = make_scheduler(clock, runner, stall_threshold=60.0)
    scheduler.arm(Action.HIBERNATE, 30)
    scheduler.poll()

    # La machine est suspendue : plus aucun passage pendant deux heures.
    clock.advance(2 * 60 * 60)
    scheduler.poll()

    assert runner.actions == []
    assert scheduler.cancellations == [CancelReason.STALL]  # type: ignore[attr-defined]
    assert not scheduler.snapshot().armed


def test_normal_jitter_does_not_trigger_stall(clock: FakeClock, runner: Recorder) -> None:
    """Un à-coup d'ordonnancement ordinaire ne doit pas annuler la tâche."""
    scheduler = make_scheduler(clock, runner, stall_threshold=60.0)
    scheduler.arm(Action.SLEEP, 10)

    run_for(scheduler, clock, 10 * 60, step=30.0)

    assert runner.actions == [Action.SLEEP]
    assert scheduler.cancellations == []  # type: ignore[attr-defined]


def test_long_idle_before_arming_is_not_a_stall(clock: FakeClock, runner: Recorder) -> None:
    """Une longue période au repos avant l'armement n'est pas une interruption."""
    scheduler = make_scheduler(clock, runner, stall_threshold=60.0)

    clock.advance(6 * 60 * 60)
    scheduler.poll()

    scheduler.arm(Action.LOCK, 1)
    run_for(scheduler, clock, 60)

    assert runner.actions == [Action.LOCK]


# -- annulation et report ----------------------------------------------------


def test_cancel_disarms(clock: FakeClock, runner: Recorder) -> None:
    scheduler = make_scheduler(clock, runner)
    scheduler.arm(Action.SHUTDOWN, 15)

    assert scheduler.cancel() is True
    assert scheduler.cancel() is False  # plus rien à annuler

    run_for(scheduler, clock, 20 * 60)
    assert runner.actions == []


def test_postpone_pushes_deadline(clock: FakeClock, runner: Recorder) -> None:
    scheduler = make_scheduler(clock, runner)
    scheduler.arm(Action.SLEEP, 10)

    run_for(scheduler, clock, 9 * 60)
    scheduler.postpone(15)
    assert scheduler.snapshot().remaining == pytest.approx(15 * 60)

    run_for(scheduler, clock, 10 * 60)
    assert runner.actions == []

    run_for(scheduler, clock, 5 * 60)
    assert runner.actions == [Action.SLEEP]


def test_postpone_without_task_does_nothing(clock: FakeClock, runner: Recorder) -> None:
    scheduler = make_scheduler(clock, runner)
    assert scheduler.postpone(15) is None


@pytest.mark.parametrize("minutes", POSTPONE_CHOICES)
def test_every_postpone_choice_pushes_the_deadline(
    clock: FakeClock, runner: Recorder, minutes: int
) -> None:
    """Chaque durée proposée à l'utilisateur doit reporter d'autant."""
    scheduler = make_scheduler(clock, runner)
    scheduler.arm(Action.HIBERNATE, 30, reminder_minutes=5)
    run_for(scheduler, clock, 26 * 60)

    scheduler.postpone(minutes)
    assert scheduler.snapshot().remaining == pytest.approx(minutes * 60)

    run_for(scheduler, clock, minutes * 60 - 30)
    assert runner.actions == []

    run_for(scheduler, clock, 30)
    assert runner.actions == [Action.HIBERNATE]


def test_short_postpone_drops_a_reminder_that_no_longer_fits(
    clock: FakeClock, runner: Recorder
) -> None:
    """Reporter de 5 min avec un rappel à 5 min le ferait tomber aussitôt."""
    reminders: list[float] = []
    scheduler = Scheduler(
        clock=clock, runner=runner, on_reminder=lambda snap: reminders.append(snap.remaining)
    )
    scheduler.arm(Action.HIBERNATE, 30, reminder_minutes=5)
    run_for(scheduler, clock, 25 * 60)
    assert len(reminders) == 1

    scheduler.postpone(5)
    run_for(scheduler, clock, 5 * 60)

    assert len(reminders) == 1
    assert runner.actions == [Action.HIBERNATE]


def test_postpone_keeps_reminder_when_it_still_fits(clock: FakeClock, runner: Recorder) -> None:
    reminders: list[float] = []
    scheduler = Scheduler(
        clock=clock, runner=runner, on_reminder=lambda snap: reminders.append(snap.remaining)
    )
    scheduler.arm(Action.HIBERNATE, 10, reminder_minutes=2)

    run_for(scheduler, clock, 8 * 60)
    assert len(reminders) == 1

    scheduler.postpone(15)
    run_for(scheduler, clock, 13 * 60)
    assert len(reminders) == 2


# -- rappel ------------------------------------------------------------------


def test_reminder_fires_ahead_of_deadline(clock: FakeClock, runner: Recorder) -> None:
    reminders: list[float] = []
    scheduler = Scheduler(
        clock=clock, runner=runner, on_reminder=lambda snap: reminders.append(snap.remaining)
    )
    scheduler.arm(Action.HIBERNATE, 30, reminder_minutes=5)

    run_for(scheduler, clock, 24 * 60)
    assert reminders == []

    run_for(scheduler, clock, 60)
    assert reminders == [pytest.approx(5 * 60)]
    assert scheduler.snapshot().state is State.REMINDING


def test_reminder_fires_only_once(clock: FakeClock, runner: Recorder) -> None:
    reminders: list[float] = []
    scheduler = Scheduler(
        clock=clock, runner=runner, on_reminder=lambda snap: reminders.append(snap.remaining)
    )
    scheduler.arm(Action.HIBERNATE, 10, reminder_minutes=2)

    run_for(scheduler, clock, 8 * 60)
    for _ in range(10):
        scheduler.poll()

    assert len(reminders) == 1


def test_reminder_longer_than_delay_is_ignored(clock: FakeClock, runner: Recorder) -> None:
    """Un rappel plus large que le délai déclencherait l'action sans préavis."""
    reminders: list[float] = []
    scheduler = Scheduler(
        clock=clock, runner=runner, on_reminder=lambda snap: reminders.append(snap.remaining)
    )
    scheduler.arm(Action.SLEEP, 3, reminder_minutes=10)

    run_for(scheduler, clock, 3 * 60)

    assert reminders == []
    assert runner.actions == [Action.SLEEP]


def test_reminding_state_still_fires(clock: FakeClock, runner: Recorder) -> None:
    scheduler = make_scheduler(clock, runner)
    scheduler.arm(Action.HIBERNATE, 10, reminder_minutes=2)

    run_for(scheduler, clock, 8 * 60)
    assert scheduler.snapshot().state is State.REMINDING

    run_for(scheduler, clock, 2 * 60)
    assert runner.actions == [Action.HIBERNATE]


def test_resume_during_reminder_cancels(clock: FakeClock, runner: Recorder) -> None:
    scheduler = make_scheduler(clock, runner)
    scheduler.arm(Action.HIBERNATE, 10, reminder_minutes=2)

    run_for(scheduler, clock, 8 * 60)
    scheduler.on_resume()

    run_for(scheduler, clock, 10 * 60)
    assert runner.actions == []


# -- robustesse --------------------------------------------------------------


def test_arm_replaces_previous_task(clock: FakeClock, runner: Recorder) -> None:
    scheduler = make_scheduler(clock, runner)
    scheduler.arm(Action.SHUTDOWN, 5)
    scheduler.arm(Action.LOCK, 20)

    run_for(scheduler, clock, 6 * 60)
    assert runner.actions == []

    run_for(scheduler, clock, 15 * 60)
    assert runner.actions == [Action.LOCK]


def test_callback_error_does_not_break_scheduling(clock: FakeClock, runner: Recorder) -> None:
    """Une interface défaillante ne doit pas laisser une tâche sans surveillance."""

    def boom(_: object) -> None:
        raise RuntimeError("interface indisponible")

    scheduler = Scheduler(clock=clock, runner=runner, on_tick=boom, on_reminder=boom)
    scheduler.arm(Action.SLEEP, 5, reminder_minutes=1)

    run_for(scheduler, clock, 5 * 60)

    assert runner.actions == [Action.SLEEP]


def test_stop_cancels_pending_task(clock: FakeClock, runner: Recorder) -> None:
    scheduler = make_scheduler(clock, runner)
    scheduler.arm(Action.HIBERNATE, 30)
    scheduler.stop()

    assert not scheduler.snapshot().armed
    assert scheduler.cancellations == [CancelReason.SHUTDOWN]  # type: ignore[attr-defined]
