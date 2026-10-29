"""Configuration persisted in the user's profile."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Final

APP_NAME = "auto-shutdown"

#: Icon applied to windows, and to the executable at build time.
ICON_FILE = "auto-shutdown.ico"

#: Postpone durations offered, in minutes. Single source: the reminder window
#: and the notification-area menu both use it.
POSTPONE_CHOICES: Final = (5, 10, 15, 30)

#: Delay bounds, in minutes. A zero delay would fire the action at the very
#: moment the task is armed, leaving no time to cancel.
MIN_DELAY_MINUTES = 1
MAX_DELAY_MINUTES = 24 * 60 * 7


def config_dir() -> Path:
    """Configuration directory (`%APPDATA%\\auto-shutdown`)."""
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / APP_NAME


def data_dir() -> Path:
    """Directory for volatile data, including the log."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_NAME


def asset_path(name: str) -> Path:
    """Path of an asset, whether running from source or from an executable.

    In `--onefile` mode, PyInstaller extracts the bundled assets into a
    temporary directory whose path is published by `sys._MEIPASS`.
    """
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled is not None:
        return Path(bundled) / "assets" / name
    return Path(__file__).resolve().parents[2] / "assets" / name


@dataclass(slots=True)
class Config:
    """Application settings.

    `action` is the name of a `power.Action` member. It is stored as a string
    so the file stays readable and hand-editable.
    """

    action: str = "HIBERNATE"
    delay_minutes: int = 30

    #: Reminder shown before the deadline, with the option to cancel or postpone.
    reminder_enabled: bool = True
    reminder_minutes: int = 5

    #: Time without keyboard/mouse input required before suspending the machine.
    #: On a system where the mouse is armed as a wake source, suspending while a
    #: movement is still in progress causes an immediate wake-up.
    input_quiet_seconds: float = 3.0

    #: Maximum wait for input to go quiet: beyond it, the action is executed
    #: anyway, since the user already had the reminder to cancel.
    input_quiet_timeout: float = 30.0

    #: Gap between two countdown polls beyond which the countdown is deemed
    #: interrupted — a sign that the machine was suspended. A deadline crossed
    #: during that interruption is cancelled rather than executed.
    stall_threshold_seconds: float = 60.0

    def path(self) -> Path:
        return config_dir() / "config.json"

    @classmethod
    def load(cls) -> Config:
        """Reload the configuration; fall back to defaults if needed.

        A corrupt or partial file must never prevent startup: unknown keys are
        ignored and missing ones keep their default.
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
        # Write then atomic replace: a power cut never leaves a truncated
        # configuration file.
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        tmp.replace(path)

    def clamped_delay(self) -> int:
        """Delay clamped to the acceptable bounds."""
        return max(MIN_DELAY_MINUTES, min(MAX_DELAY_MINUTES, int(self.delay_minutes)))

    def effective_reminder_minutes(self) -> int:
        """Reminder lead time, never greater than or equal to the delay itself.

        A reminder scheduled beyond the deadline would never fire; a reminder
        exactly at the deadline would leave no time to react.
        """
        if not self.reminder_enabled:
            return 0
        return max(0, min(int(self.reminder_minutes), self.clamped_delay() - 1))
