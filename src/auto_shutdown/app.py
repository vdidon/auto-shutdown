"""Wiring of the three components and their threads.

Division of roles:

- main thread: tkinter loop (`Ui.run`);
- `tray` thread: Windows window, menu and power notifications;
- `scheduler` thread: countdown and triggering.

Anything touching tkinter is rerouted to the main thread by `Ui.call`. The
other two components are designed to be called from any thread.
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
from .i18n import detect_language, set_language, tr
from .power import Action
from .scheduler import CancelReason, Scheduler, Snapshot, State
from .tray import Tray, TrayCallbacks
from .ui import Ui, UiCallbacks, action_label, format_duration, status_text

log = logging.getLogger(__name__)

MUTEX_NAME = "Local\\AutoShutdownSingleInstance"


def _enable_dpi_awareness() -> None:
    """Keep the interface sharp on high-density displays.

    Without this, Windows stretches the interface and the text becomes blurry.
    Failure of the call is harmless: only the looks suffer.
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            log.debug("Unable to enable DPI awareness")


class Application:
    """Full lifecycle of the application."""

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

    # -- lifecycle ---------------------------------------------------------

    def run(self) -> int:
        self._scheduler.start()
        self._tray_thread.start()
        if not self._tray.wait_ready():
            log.error("The notification area did not respond; stopping")
            return 1

        self._refresh_tray(self._scheduler.snapshot())
        if self._open_config:
            # Scheduled rather than called: the window must be created inside
            # the tkinter loop, which `run` starts right after.
            self._ui.call(self._ui.show_config)
        log.info("Application started")
        self._ui.run()
        log.info("Application stopped")
        return 0

    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self._scheduler.stop()
        self._tray.shutdown()
        self._ui.quit()

    # -- commands ----------------------------------------------------------

    def _arm(self, action: Action, delay_minutes: int, reminder_minutes: int) -> None:
        snapshot = self._scheduler.arm(action, delay_minutes, reminder_minutes)
        self._refresh_tray(snapshot)
        self._tray.notify(
            tr("notify.armed.title"),
            tr(
                "notify.armed.body",
                action=action.label,
                remaining=format_duration(snapshot.remaining),
            ),
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
        self._tray.notify(
            tr("notify.postponed.title"), tr("notify.postponed.body", minutes=minutes)
        )

    def _open_log(self) -> None:
        path = log_module.log_path()
        try:
            os.startfile(path)
        except OSError:
            log.exception("Unable to open the log file %s", path)

    def _query_state(self) -> tuple[bool, str]:
        snapshot = self._scheduler.snapshot()
        return snapshot.armed, status_text(snapshot)

    # -- reactions to the scheduler ----------------------------------------

    def _on_tick(self, snapshot: Snapshot) -> None:
        self._refresh_tray(snapshot)
        self._ui.call(self._ui.refresh)

    def _on_reminder(self, snapshot: Snapshot) -> None:
        self._ui.call(self._ui.show_reminder, snapshot)
        self._tray.notify(
            tr("notify.reminder.title"),
            tr(
                "notify.reminder.body",
                action=action_label(snapshot),
                remaining=format_duration(snapshot.remaining),
            ),
            warning=True,
        )

    def _on_fired(self, action: Action) -> None:
        self._ui.call(self._ui.close_reminder)
        self._refresh_tray(self._scheduler.snapshot())
        log.info("Triggering %s", action.name)

    def _on_cancelled(self, reason: CancelReason) -> None:
        self._ui.call(self._ui.close_reminder)
        self._ui.call(self._ui.refresh)
        self._refresh_tray(self._scheduler.snapshot())
        # Make the cancellation visible: that is precisely what the user must
        # be able to notice, rather than suffer an unexplained return to sleep.
        keys = {
            CancelReason.RESUME: "notify.cancelled.resume",
            CancelReason.STALL: "notify.cancelled.stall",
        }
        key = keys.get(reason)
        if key is not None:
            self._tray.notify(tr("notify.cancelled.title"), tr(key), warning=True)

    # -- presentation ------------------------------------------------------

    def _refresh_tray(self, snapshot: Snapshot) -> None:
        if snapshot.state is State.REMINDING:
            color = tray_module.COLOR_REMINDING
        elif snapshot.armed:
            color = tray_module.COLOR_ARMED
        else:
            color = tray_module.COLOR_IDLE

        tooltip = f"Auto Shutdown\n{status_text(snapshot)}"

        # The scheduler ticks four times per second; the tooltip only changes
        # once per second. Filtering avoids that many round trips to the shell.
        if tooltip == self._last_tooltip:
            return
        self._last_tooltip = tooltip
        self._tray.set_state(color, tooltip)


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        prog="auto-shutdown",
        description="Schedule a delayed sleep, hibernate, shutdown or lock.",
    )
    parser.add_argument("--version", action="version", version=f"auto-shutdown {__version__}")
    parser.add_argument("--verbose", action="store_true", help="detailed logging to the console")
    parser.add_argument(
        "--minimized",
        action="store_true",
        help="start in the notification area without opening the configuration window "
        "(meant for automatic launch at sign-in)",
    )
    args = parser.parse_args(argv)

    path = log_module.setup(verbose=args.verbose)
    # First line of every session: without it, a log reported by a user does
    # not say which version produced it.
    log.info("auto-shutdown %s — log: %s", __version__, path)

    mutex = winapi.acquire_single_instance_mutex(MUTEX_NAME)
    if mutex is None:
        log.error("Another instance is already running")
        return 2

    set_language(detect_language())
    _enable_dpi_awareness()
    winapi.enable_shutdown_privilege()

    config = Config.load()
    try:
        return Application(config, open_config=not args.minimized).run()
    finally:
        winapi.kernel32.CloseHandle(mutex)
