"""Single-task scheduler, designed to never fire twice.

Four rules carry most of the reliability:

1. **Monotonic time base.** The deadline is a `time.monotonic()` instant, not a
   date. A system clock change, a time zone change or an NTP adjustment
   therefore cannot make the deadline suddenly "elapsed".
2. **Disarm before executing.** The task leaves the armed state *before* the
   action is launched. There is no instant at which a task that has already
   fired remains armed.
3. **Cancel on resume from sleep.** Any resume cancels a task that is still
   armed. This is what rules out the "wake up -> immediately fall asleep again"
   loop: after a resume, only the user can re-arm.
4. **Countdown interruption detection.** If two successive polls are separated
   by far more than the polling period, the process was frozen — the machine
   was suspended. A deadline crossed during that freeze is cancelled instead
   of being executed.

Rule 4 is the safety net for rule 3. With modern standby (`S0 Low Power Idle`),
the monotonic clock keeps advancing during sleep: a deadline can therefore be
crossed with nobody there to see it. If the resume notification were ever
missed, the action would fire within a second of waking up — exactly the defect
this project fixes. Rule 4 does not depend on any Windows notification.
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

#: Polling period. Fine enough for a per-second countdown, coarse enough for
#: zero CPU cost.
TICK_SECONDS = 0.25

#: Beyond this gap between two polls, the countdown is considered to have been
#: interrupted. Large compared to `TICK_SECONDS` and to any OS scheduling
#: hiccup, short compared to any real sleep.
STALL_THRESHOLD_SECONDS = 60.0


class State(Enum):
    IDLE = auto()
    ARMED = auto()
    REMINDING = auto()


class CancelReason(Enum):
    USER = "cancelled by the user"
    RESUME = "cancelled automatically on resume from sleep"
    STALL = "cancelled: the countdown was interrupted"
    SHUTDOWN = "application shutting down"


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Immutable point-in-time view of the state, safe to read from another thread."""

    state: State
    action: Action | None
    remaining: float
    reminder_active: bool

    @property
    def armed(self) -> bool:
        return self.state in (State.ARMED, State.REMINDING)


class Scheduler:
    """Manage a single task and its countdown.

    Callbacks are invoked from the internal thread: it is up to the caller to
    forward them to its UI thread.
    """

    def __init__(  # noqa: PLR0913  (settings and callbacks, all named and optional)
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
        # `clock` and `runner` are injectable so the deadline logic can be
        # tested without waiting in real time or putting the machine to sleep.
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

    # -- lifecycle ---------------------------------------------------------

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

    # -- commands ----------------------------------------------------------

    def arm(self, action: Action, delay_minutes: int, reminder_minutes: int = 0) -> Snapshot:
        """Arm the task to fire in `delay_minutes` minutes."""
        now = self._clock()
        delay = max(0, int(delay_minutes)) * 60.0
        with self._lock:
            self._action = action
            self._deadline = now + delay
            reminder = max(0, int(reminder_minutes)) * 60.0
            # A reminder only makes sense if it falls in the future and before the deadline.
            self._reminder_at = now + delay - reminder if 0 < reminder < delay else None
            self._state = State.ARMED
            # Restart from the present instant: the time elapsed before arming
            # must not be counted as a countdown interruption.
            self._last_poll = now
            snapshot = self._snapshot_locked(now)
        log.info(
            "Task armed: %s in %d min (reminder %s)",
            action.name,
            delay_minutes,
            f"{reminder_minutes} min before" if self._reminder_at else "disabled",
        )
        self._wake.set()
        return snapshot

    def cancel(self, reason: CancelReason = CancelReason.USER) -> bool:
        """Disarm the task. Return `True` if a task was actually armed."""
        with self._lock:
            if self._state not in (State.ARMED, State.REMINDING):
                return False
            action = self._action
            self._reset()
        log.info("Task %s cancelled (%s)", action.name if action else "?", reason.value)
        self._wake.set()
        self._notify(self._on_cancelled, reason)
        return True

    def postpone(self, minutes: int) -> Snapshot | None:
        """Push the deadline back to `minutes` from now.

        The reminder is kept with the same lead time, unless that no longer
        fits within the new delay.
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

    # -- power notifications -----------------------------------------------

    def on_suspend(self) -> None:
        """The system is going to sleep (`PBT_APMSUSPEND`)."""
        log.info("System notification: entering sleep")

    def on_resume(self) -> None:
        """The system is resuming from sleep (`PBT_APMRESUME*`).

        Core of the fix. A task that is still armed is cancelled rather than
        left running: without this, a deadline perceived as elapsed fires within
        seconds of the resume and puts the machine back to sleep.

        Windows often emits `PBT_APMRESUMESUSPEND` then
        `PBT_APMRESUMEAUTOMATIC` for a single resume: the handling is therefore
        idempotent.
        """
        with self._lock:
            armed = self._state in (State.ARMED, State.REMINDING)
            if armed:
                self._reset()
            # The countdown resumes from here: the interval spent asleep must
            # not be counted twice by the interruption detection.
            self._last_poll = self._clock()
        log.info(
            "System notification: resume from sleep%s",
            " — armed task cancelled" if armed else "",
        )
        self._wake.set()
        if armed:
            self._notify(self._on_cancelled, CancelReason.RESUME)

    # -- reading -----------------------------------------------------------

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

    # -- internal loop -----------------------------------------------------

    def _reset(self) -> None:
        """Return the state to idle. Call only while holding the lock."""
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
        """Advance the scheduler by one step.

        Called by the internal loop; public so the scheduler can be driven
        with a simulated clock.
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

            # Rule 4: a gap in the countdown signals a suspended machine.
            # A deadline crossed during that gap is not played.
            if previous_poll is not None and now - previous_poll > self._stall_threshold:
                stalled = True
                self._reset()
            elif now >= self._deadline:
                # Rule 2: disarm first, execute afterwards. If the action
                # returns (resume from sleep), nothing is left armed.
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
                "Countdown interrupted for %.0f s: task cancelled as a precaution",
                now - (previous_poll or now),
            )
            self._notify(self._on_cancelled, CancelReason.STALL)
            return
        if due_action is not None:
            self._fire(due_action)
            return
        if reminder_snapshot is not None:
            log.info(
                "Reminder: %s in %.0f s",
                reminder_snapshot.action.name if reminder_snapshot.action else "?",
                reminder_snapshot.remaining,
            )
            self._notify(self._on_reminder, reminder_snapshot)
        self._notify(self._on_tick, tick_snapshot)

    def _fire(self, action: Action) -> None:
        self._notify(self._on_fired, action)
        self._runner(action)

    def _default_runner(self, action: Action) -> None:
        # `execute` blocks until wake-up for a sleep: it needs its own thread,
        # otherwise the loop would no longer see cancellations or power
        # notifications go by.
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
            log.exception("Action %s failed", action.name)

    def _notify[T](self, callback: Callable[[T], None] | None, value: T) -> None:
        """Invoke a callback without ever letting an exception propagate.

        A UI error must not kill the scheduling thread, which would risk leaving
        an armed task that nothing is watching anymore.
        """
        if callback is None:
            return
        try:
            callback(value)
        except Exception:
            log.exception("Error in a scheduler callback")
