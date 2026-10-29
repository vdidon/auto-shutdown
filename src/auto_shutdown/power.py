"""Power actions and the precautions surrounding them."""

from __future__ import annotations

import ctypes
import logging
import time
from enum import Enum, auto

from . import winapi
from .i18n import tr

log = logging.getLogger(__name__)


class Action(Enum):
    """Action executed at the deadline."""

    HIBERNATE = auto()
    SLEEP = auto()
    SHUTDOWN = auto()
    RESTART = auto()
    LOGOFF = auto()
    LOCK = auto()

    @property
    def label(self) -> str:
        """Name shown in the interface, in the user's language."""
        return tr(f"action.{self.name}")

    @property
    def suspends(self) -> bool:
        """True if the action suspends the machine.

        These actions return control on resume, unlike a shutdown or a
        restart — which requires neutralising any task still armed when the
        machine wakes up.
        """
        return self in (Action.HIBERNATE, Action.SLEEP)

    @property
    def is_terminal(self) -> bool:
        """True if the action ends the process (shutdown, restart, sign-out)."""
        return self in (Action.SHUTDOWN, Action.RESTART, Action.LOGOFF)

    @classmethod
    def parse(cls, name: str) -> Action:
        """Convert a name stored in the configuration, with a safe fallback."""
        try:
            return cls[name]
        except KeyError:
            log.warning("Unknown action %r, falling back to HIBERNATE", name)
            return cls.HIBERNATE


def wait_for_input_quiet(quiet_seconds: float, timeout: float) -> bool:
    """Wait for a period without keyboard/mouse input before suspending.

    On this machine, `powercfg /devicequery wake_armed` only returns the
    mouse: a `SetSuspendState` call issued while a movement is still being
    processed wakes the system back up within a second. Waiting for quiet
    removes that bounce.

    Return `True` if quiet was obtained, `False` if the wait ceiling was
    reached — in which case the caller runs the action anyway, since the user
    has already had the chance to cancel it through the reminder.
    """
    if quiet_seconds <= 0:
        return True
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        idle = winapi.idle_seconds()
        if idle >= quiet_seconds:
            return True
        # Sleep just the missing amount, capped to stay responsive.
        time.sleep(min(quiet_seconds - idle, 1.0))
    log.warning(
        "Input still active after waiting %.0f s: executing anyway",
        timeout,
    )
    return False


def execute(action: Action, *, quiet_seconds: float = 0.0, quiet_timeout: float = 30.0) -> None:
    """Execute the requested action.

    For a sleep, the `SetSuspendState` call is blocking: it only returns
    when the machine wakes up.
    """
    if action.suspends:
        wait_for_input_quiet(quiet_seconds, quiet_timeout)

    log.info("Executing action %s", action.name)

    if action is Action.LOCK:
        if not winapi.user32.LockWorkStation():
            _raise_last_error("LockWorkStation")
        return

    if action.suspends:
        hibernate = action is Action.HIBERNATE
        # Third parameter (bWakeupEventsDisabled) left at False: Windows has
        # ignored it since Vista, so passing True prevents nothing.
        if not winapi.powrprof.SetSuspendState(hibernate, False, False):
            _raise_last_error("SetSuspendState")
        log.info("Resumed after %s", action.name)
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
    raise OSError(code, f"{call} failed (code {code})")
