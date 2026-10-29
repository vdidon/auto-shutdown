"""Checks for the dispatching of notification-area menu commands.

No window is created: `_on_command` only depends on the identifiers and the
callbacks.
"""

from __future__ import annotations

import pytest

from auto_shutdown.config import POSTPONE_CHOICES
from auto_shutdown.tray import (
    CMD_CANCEL,
    CMD_CONFIGURE,
    CMD_OPEN_LOG,
    CMD_POSTPONE_BASE,
    CMD_QUIT,
    Tray,
    TrayCallbacks,
)


class Spy:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.postponed: list[int] = []

    def callbacks(self) -> TrayCallbacks:
        return TrayCallbacks(
            on_configure=lambda: self.calls.append("configure"),
            on_cancel=lambda: self.calls.append("cancel"),
            on_postpone=self.postponed.append,
            on_open_log=lambda: self.calls.append("log"),
            on_quit=lambda: self.calls.append("quit"),
            on_suspend=lambda: self.calls.append("suspend"),
            on_resume=lambda: self.calls.append("resume"),
            query_state=lambda: (False, "No task scheduled"),
        )


@pytest.fixture
def spy() -> Spy:
    return Spy()


@pytest.mark.parametrize(("index", "minutes"), list(enumerate(POSTPONE_CHOICES)))
def test_submenu_entry_maps_to_its_duration(spy: Spy, index: int, minutes: int) -> None:
    tray = Tray(spy.callbacks())
    tray._on_command(CMD_POSTPONE_BASE + index)
    assert spy.postponed == [minutes]
    assert spy.calls == []


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (CMD_CONFIGURE, "configure"),
        (CMD_CANCEL, "cancel"),
        (CMD_OPEN_LOG, "log"),
        (CMD_QUIT, "quit"),
    ],
)
def test_fixed_commands_keep_their_handler(spy: Spy, command: int, expected: str) -> None:
    tray = Tray(spy.callbacks())
    tray._on_command(command)
    assert spy.calls == [expected]
    assert spy.postponed == []


def test_identifier_ranges_do_not_overlap() -> None:
    """Fixed commands must never fall within the submenu range."""
    fixed = {CMD_CONFIGURE, CMD_CANCEL, CMD_OPEN_LOG, CMD_QUIT}
    submenu = {CMD_POSTPONE_BASE + i for i in range(len(POSTPONE_CHOICES))}
    assert not fixed & submenu


def test_unknown_command_is_ignored(spy: Spy) -> None:
    tray = Tray(spy.callbacks())
    tray._on_command(9999)
    assert spy.calls == []
    assert spy.postponed == []
