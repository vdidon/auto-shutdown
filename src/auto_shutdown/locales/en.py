"""English interface texts: the reference catalog, and the fallback for any other."""

from typing import Final

MESSAGES: Final[dict[str, str]] = {
    # Actions, as listed in the configuration window.
    "action.HIBERNATE": "Hibernate",
    "action.SLEEP": "Sleep",
    "action.SHUTDOWN": "Shut down",
    "action.RESTART": "Restart",
    "action.LOGOFF": "Sign out",
    "action.LOCK": "Lock the screen",
    "action.unknown": "The scheduled action",
    # Task state, shared by the configuration window, tray tooltip and menu.
    "status.armed": "{action} in {remaining}",
    "status.idle": "No task scheduled",
    # Configuration window.
    "config.action": "Action to run",
    "config.delay": "Starting now, in",
    "config.hours": "hour(s)",
    "config.minutes": "minute(s)",
    "config.remind": "Remind me",
    "config.remind_before": "minute(s) before",
    "config.close": "Close",
    "config.cancel_task": "Cancel task",
    "config.start": "Start",
    "config.version": "version {version}",
    "config.error.not_integer": "The delay must be a whole number.",
    "config.error.too_short": "The delay must be at least one minute.",
    "config.error.too_long": "The delay cannot exceed seven days.",
    # Reminder window.
    "reminder.title": "Auto Shutdown — reminder",
    "reminder.heading": "{action} in",
    "reminder.postpone": "Postpone by",
    "reminder.postpone_choice": "{minutes} min",
    "reminder.cancel": "Cancel",
    "reminder.dismiss": "Let it run",
    # Tray context menu.
    "menu.configure": "Configure and arm…",
    "menu.postpone": "Postpone by",
    "menu.postpone_choice": "{minutes} minutes",
    "menu.cancel": "Cancel task",
    "menu.open_log": "Open log",
    "menu.quit": "Quit",
    # Tray notifications.
    "notify.armed.title": "Task scheduled",
    "notify.armed.body": "{action} in {remaining}.",
    "notify.postponed.title": "Task postponed",
    "notify.postponed.body": "New deadline in {minutes} minutes.",
    "notify.reminder.title": "Reminder",
    "notify.reminder.body": "{action} in {remaining}.",
    "notify.cancelled.title": "Task cancelled",
    "notify.cancelled.resume": (
        "The computer woke up: the scheduled task was cancelled to avoid sending it back to sleep."
    ),
    "notify.cancelled.stall": (
        "The countdown was interrupted, a sign that the computer was suspended. "
        "The task was cancelled to be safe."
    ),
}
