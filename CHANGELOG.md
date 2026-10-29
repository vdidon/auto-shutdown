# Changelog

The project follows [Semantic Versioning](https://semver.org/):
`MAJOR.MINOR.PATCH`.

- **MAJOR** — breaking change: incompatible configuration format, removed
  command-line option, or a default behavior changed in a way that would
  surprise an existing user.
- **MINOR** — backward-compatible addition: a new action, trigger or setting.
- **PATCH** — bug fix or internal improvement with no visible effect on
  existing settings.

The number lives in `src/auto_shutdown/__init__.py` and in `pyproject.toml`; a
test prevents the two from diverging, and requires an entry here for the
current version.

---

## 0.1.0

First release.

### Scheduling

- Triggers after a delay expressed in hours and minutes.
- Six actions: hibernate, sleep, shut down, restart, sign out, lock the screen.
- Reminder before the deadline, with the choice to cancel, postpone or proceed.
- Postpone by 5, 10, 15 or 30 minutes, from the reminder as well as from the
  notification-area menu.

### Reliability

The defect being targeted is a task firing again when the machine resumes from
sleep, which sends it back to sleep a few seconds after every wake-up. Four
mechanisms prevent it:

- the deadline is based on a monotonic clock, so clock changes do not affect it;
- the task is disarmed before the action runs;
- the task is cancelled automatically on resume, with a notification;
- the task is cancelled when the countdown was interrupted for more than a
  minute, a sign of a suspended machine — this safety net does not depend on
  any Windows notification.

On top of that, the app waits for a period without keyboard or mouse activity
before any suspend, which avoids an immediate wake-up on machines whose mouse
is armed to wake them.

### Interface

- Notification icon whose color reflects the state, context menu, tooltips.
- Configuration window opened at launch; `--minimized` suppresses it, for
  automatic launch at sign-in.
- Timestamped log of every arming, cancellation, trigger and power transition,
  which can be opened from the menu.
- English and French interface, following the Windows display language;
  any other language falls back to English.

### Distribution

- No runtime dependency: `ctypes` and `tkinter` are enough.
- Standalone executable of about 12 MB built by `build.ps1`.
- Icon generated in pure Python, without Pillow.
