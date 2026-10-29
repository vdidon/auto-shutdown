"""tkinter interface: the configuration window and the reminder window.

Tkinter can only be driven from the thread that created its root window. That
root therefore lives in the main thread, and every request coming from the tray
or the scheduler goes through `Ui.call`, which reroutes the call via `after`.
"""

from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from tkinter import ttk

from . import __version__
from .config import (
    ICON_FILE,
    MAX_DELAY_MINUTES,
    MIN_DELAY_MINUTES,
    POSTPONE_CHOICES,
    Config,
    asset_path,
)
from .i18n import tr
from .power import Action
from .scheduler import Snapshot

log = logging.getLogger(__name__)


def format_duration(seconds: float) -> str:
    """Format a duration as `HH:MM:SS`, rounded up to the next second."""
    total = max(0, int(seconds + 0.5))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def action_label(snapshot: Snapshot) -> str:
    """Interface name of the scheduled action."""
    return snapshot.action.label if snapshot.action is not None else tr("action.unknown")


def status_text(snapshot: Snapshot) -> str:
    """One-line task state, shared by the configuration window and the tray."""
    if snapshot.armed:
        return tr(
            "status.armed",
            action=action_label(snapshot),
            remaining=format_duration(snapshot.remaining),
        )
    return tr("status.idle")


@dataclass(slots=True)
class UiCallbacks:
    """Actions triggered by the interface."""

    #: `(action, delay in minutes, reminder lead time in minutes)`
    on_arm: Callable[[Action, int, int], None]
    on_cancel: Callable[[], None]
    on_postpone: Callable[[int], None]
    on_quit: Callable[[], None]
    snapshot: Callable[[], Snapshot]


class Ui:
    """tkinter root and the application's windows."""

    def __init__(self, config: Config, callbacks: UiCallbacks) -> None:
        self._config = config
        self._cb = callbacks
        self._root = tk.Tk()
        self._root.withdraw()
        self._apply_icon()
        # Closing the last window must not stop the application: it keeps
        # living in the notification area.
        self._root.protocol("WM_DELETE_WINDOW", lambda: None)
        self._config_window: ConfigWindow | None = None
        self._reminder_window: ReminderWindow | None = None

    # -- lifecycle ---------------------------------------------------------

    def run(self) -> None:
        """Main loop; only returns when the application stops."""
        self._root.mainloop()

    def call(self, fn: Callable[..., None], *args: object) -> None:
        """Run `fn` in the interface thread. Callable from any thread."""
        try:
            self._root.after(0, lambda: self._guarded(fn, *args))
        except RuntimeError:
            # The root is already destroyed: the application is shutting down.
            log.debug("UI call ignored, root destroyed")

    def quit(self) -> None:
        self.call(self._root.destroy)

    def _apply_icon(self) -> None:
        """Apply the application icon to all windows.

        `default=` propagates it to the `Toplevel` windows created afterwards.
        Its absence is not an error: Tk's generic icon is simply shown instead.
        """
        icon = asset_path(ICON_FILE)
        if not icon.is_file():
            # The icon is versioned and bundled in the executable: its absence
            # points to a packaging defect, not a normal situation.
            log.warning("Icon not found: %s", icon)
            return
        try:
            self._root.iconbitmap(default=str(icon))
        except tk.TclError:
            log.warning("Icon rejected by Tk: %s", icon)
        else:
            log.debug("Icon applied: %s", icon)

    @staticmethod
    def _guarded(fn: Callable[..., None], *args: object) -> None:
        try:
            fn(*args)
        except Exception:
            log.exception("Error in an interface function")

    # -- windows -----------------------------------------------------------

    def show_config(self) -> None:
        if self._config_window is not None and self._config_window.alive:
            self._config_window.focus()
            return
        self._config_window = ConfigWindow(self._root, self._config, self._cb)
        # Without this, the window appears behind those already open — notably
        # at launch, when nothing has drawn attention to it yet.
        self._config_window.focus()

    def show_reminder(self, snapshot: Snapshot) -> None:
        if self._reminder_window is not None and self._reminder_window.alive:
            return
        self._reminder_window = ReminderWindow(self._root, self._cb, snapshot)

    def close_reminder(self) -> None:
        if self._reminder_window is not None:
            self._reminder_window.close()
            self._reminder_window = None

    def refresh(self) -> None:
        """Refresh the countdown in the open windows."""
        if self._config_window is not None and self._config_window.alive:
            self._config_window.refresh_status()


class ConfigWindow:
    """Choice of action, delay and reminder, then arming."""

    def __init__(self, root: tk.Tk, config: Config, callbacks: UiCallbacks) -> None:
        self._config = config
        self._cb = callbacks
        self.alive = True

        self._win = tk.Toplevel(root)
        self._win.title("Auto Shutdown")
        self._win.resizable(width=False, height=False)
        self._win.protocol("WM_DELETE_WINDOW", self.close)

        frame = ttk.Frame(self._win, padding=16)
        frame.grid(sticky="nsew")

        ttk.Label(frame, text=tr("config.action")).grid(row=0, column=0, sticky="w", pady=(0, 4))
        self._actions = list(Action)
        self._action_box = ttk.Combobox(
            frame,
            values=[a.label for a in self._actions],
            state="readonly",
            width=28,
        )
        self._action_box.current(self._actions.index(Action.parse(config.action)))
        self._action_box.grid(row=1, column=0, columnspan=3, sticky="we", pady=(0, 12))

        ttk.Label(frame, text=tr("config.delay")).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(0, 4)
        )

        delay = config.clamped_delay()
        self._hours_var = tk.StringVar(value=str(delay // 60))
        self._minutes_var = tk.StringVar(value=str(delay % 60))

        delay_row = ttk.Frame(frame)
        delay_row.grid(row=3, column=0, columnspan=3, sticky="w", pady=(0, 12))
        ttk.Spinbox(
            delay_row, from_=0, to=167, width=5, textvariable=self._hours_var, wrap=False
        ).grid(row=0, column=0)
        ttk.Label(delay_row, text=tr("config.hours")).grid(row=0, column=1, padx=(6, 16))
        ttk.Spinbox(
            delay_row, from_=0, to=59, width=5, textvariable=self._minutes_var, wrap=False
        ).grid(row=0, column=2)
        ttk.Label(delay_row, text=tr("config.minutes")).grid(row=0, column=3, padx=(6, 0))

        self._reminder_var = tk.BooleanVar(value=config.reminder_enabled)
        self._reminder_minutes_var = tk.StringVar(value=str(config.reminder_minutes))
        reminder_row = ttk.Frame(frame)
        reminder_row.grid(row=4, column=0, columnspan=3, sticky="w", pady=(0, 4))
        ttk.Checkbutton(
            reminder_row,
            text=tr("config.remind"),
            variable=self._reminder_var,
            command=self._sync_reminder_state,
        ).grid(row=0, column=0)
        self._reminder_spin = ttk.Spinbox(
            reminder_row, from_=1, to=120, width=5, textvariable=self._reminder_minutes_var
        )
        self._reminder_spin.grid(row=0, column=1, padx=(6, 6))
        ttk.Label(reminder_row, text=tr("config.remind_before")).grid(row=0, column=2)
        self._sync_reminder_state()

        self._status_var = tk.StringVar(value="")
        ttk.Separator(frame, orient="horizontal").grid(
            row=5, column=0, columnspan=3, sticky="we", pady=12
        )
        ttk.Label(frame, textvariable=self._status_var).grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(0, 12)
        )

        buttons = ttk.Frame(frame)
        buttons.grid(row=7, column=0, columnspan=3, sticky="e")
        ttk.Button(buttons, text=tr("config.close"), command=self.close).grid(
            row=0, column=0, padx=(0, 8)
        )
        self._cancel_button = ttk.Button(
            buttons, text=tr("config.cancel_task"), command=self._on_cancel
        )
        self._cancel_button.grid(row=0, column=1, padx=(0, 8))
        ttk.Button(buttons, text=tr("config.start"), command=self._on_start).grid(row=0, column=2)

        self._error_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self._error_var, foreground="#c0392b").grid(
            row=8, column=0, columnspan=3, sticky="w", pady=(8, 0)
        )

        # Discreet but always visible: removes any ambiguity about which
        # version is actually running, notably between an executable and the
        # sources.
        ttk.Label(
            frame,
            text=tr("config.version", version=__version__),
            font=("Segoe UI", 8),
            foreground="#8a9099",
        ).grid(row=9, column=0, columnspan=3, sticky="w", pady=(14, 0))

        self.refresh_status()
        self._centre(root)
        self._win.after(1000, self._tick)

    # -- events ------------------------------------------------------------

    def _sync_reminder_state(self) -> None:
        self._reminder_spin.state(["!disabled"] if self._reminder_var.get() else ["disabled"])

    def _read_delay(self) -> int | None:
        """Read the entered delay; return `None` and show the error if invalid."""
        try:
            hours = int(self._hours_var.get())
            minutes = int(self._minutes_var.get())
        except ValueError:
            self._error_var.set(tr("config.error.not_integer"))
            return None
        total = hours * 60 + minutes
        if total < MIN_DELAY_MINUTES:
            self._error_var.set(tr("config.error.too_short"))
            return None
        if total > MAX_DELAY_MINUTES:
            self._error_var.set(tr("config.error.too_long"))
            return None
        return total

    def _read_reminder(self, delay: int) -> int:
        if not self._reminder_var.get():
            return 0
        try:
            minutes = int(self._reminder_minutes_var.get())
        except ValueError:
            return 0
        # A reminder falling at or after the deadline would be pointless.
        return max(0, min(minutes, delay - 1))

    def _on_start(self) -> None:
        delay = self._read_delay()
        if delay is None:
            return
        self._error_var.set("")
        action = self._actions[self._action_box.current()]
        reminder = self._read_reminder(delay)

        self._config.action = action.name
        self._config.delay_minutes = delay
        self._config.reminder_enabled = self._reminder_var.get()
        if reminder:
            self._config.reminder_minutes = reminder
        self._config.save()

        self._cb.on_arm(action, delay, reminder)
        self.refresh_status()

    def _on_cancel(self) -> None:
        self._cb.on_cancel()
        self.refresh_status()

    def _tick(self) -> None:
        if not self.alive:
            return
        self.refresh_status()
        self._win.after(1000, self._tick)

    def refresh_status(self) -> None:
        if not self.alive:
            return
        snapshot = self._cb.snapshot()
        self._status_var.set(status_text(snapshot))
        self._cancel_button.state(["!disabled"] if snapshot.armed else ["disabled"])

    def focus(self) -> None:
        self._win.deiconify()
        self._win.lift()
        self._win.focus_force()

    def close(self) -> None:
        self.alive = False
        self._win.destroy()

    def _centre(self, root: tk.Tk) -> None:
        self._win.update_idletasks()
        width = self._win.winfo_width()
        height = self._win.winfo_height()
        x = (root.winfo_screenwidth() - width) // 2
        y = (root.winfo_screenheight() - height) // 3
        self._win.geometry(f"+{x}+{y}")


class ReminderWindow:
    """Warning shown before the deadline, with cancel and postpone options."""

    def __init__(self, root: tk.Tk, callbacks: UiCallbacks, snapshot: Snapshot) -> None:
        self._cb = callbacks
        self.alive = True

        self._win = tk.Toplevel(root)
        self._win.title(tr("reminder.title"))
        self._win.resizable(width=False, height=False)
        self._win.attributes("-topmost", True)
        self._win.protocol("WM_DELETE_WINDOW", self.close)

        frame = ttk.Frame(self._win, padding=20)
        frame.grid()

        heading = tr("reminder.heading", action=action_label(snapshot))
        ttk.Label(frame, text=heading, font=("Segoe UI", 11)).grid(row=0, column=0)

        self._countdown_var = tk.StringVar(value=format_duration(snapshot.remaining))
        ttk.Label(frame, textvariable=self._countdown_var, font=("Segoe UI", 26, "bold")).grid(
            row=1, column=0, pady=(4, 16)
        )

        postpone = ttk.Frame(frame)
        postpone.grid(row=2, column=0, pady=(0, 12))
        ttk.Label(postpone, text=tr("reminder.postpone")).grid(row=0, column=0, padx=(0, 8))
        for index, minutes in enumerate(POSTPONE_CHOICES):
            # `minutes=minutes` freezes the value: without it, all four buttons
            # would share the loop's last value.
            ttk.Button(
                postpone,
                text=tr("reminder.postpone_choice", minutes=minutes),
                width=7,
                command=lambda minutes=minutes: self._on_postpone(minutes),
            ).grid(row=0, column=index + 1, padx=2)

        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0)
        ttk.Button(buttons, text=tr("reminder.cancel"), command=self._on_cancel).grid(
            row=0, column=0, padx=4
        )
        ttk.Button(buttons, text=tr("reminder.dismiss"), command=self.close).grid(
            row=0, column=1, padx=4
        )

        self._centre(root)
        # The window grabs attention once, then stops staying in front of the
        # others so it doesn't get in the way of ongoing work.
        self._win.focus_force()
        self._win.after(1500, lambda: self._win.attributes("-topmost", False))
        self._tick()

    def _tick(self) -> None:
        if not self.alive:
            return
        snapshot = self._cb.snapshot()
        if not snapshot.armed:
            self.close()
            return
        self._countdown_var.set(format_duration(snapshot.remaining))
        self._win.after(500, self._tick)

    def _on_cancel(self) -> None:
        self._cb.on_cancel()
        self.close()

    def _on_postpone(self, minutes: int) -> None:
        self._cb.on_postpone(minutes)
        self.close()

    def close(self) -> None:
        if not self.alive:
            return
        self.alive = False
        self._win.destroy()

    def _centre(self, root: tk.Tk) -> None:
        self._win.update_idletasks()
        width = self._win.winfo_width()
        height = self._win.winfo_height()
        x = (root.winfo_screenwidth() - width) // 2
        y = (root.winfo_screenheight() - height) // 3
        self._win.geometry(f"+{x}+{y}")
