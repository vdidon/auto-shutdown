# Reliability across sleep and resume

This document explains the defect this program was designed to avoid, the rules
that protect it, and the causes of spurious wake-ups that come from the
machine's configuration rather than from the software.

## The problem

On a machine with modern standby, the following sequence shows up in the
Windows event log:

| Time | Event | Interpretation |
|---|---|---|
| 08:14:49 | Power-Troubleshooter | the machine resumes from sleep |
| 08:14:51 | Kernel-Power **187** | a process calls `SetSuspendState` |
| 08:14:56 | Kernel-Power **42** | the machine goes back to sleep |
| 08:15:02 | Kernel-Power **107** | it wakes up again |

Two seconds after the wake-up, the scheduling utility runs its action again. The
user sees the PC turn on, briefly show the boot screen, then go back to sleep —
sometimes several times in a row.

The cause is almost always the same: the deadline is stored as an **absolute
time**, and the task is not disarmed. On wake-up that time is in the past, so
the condition is true and the action fires again immediately.

## How this program guards against it

Four rules, all verified by the test suite:

1. **Monotonic time base.** The deadline is a `time.monotonic()` instant, not a
   date. A system clock change, a time zone change or an NTP adjustment cannot
   suddenly make it "overdue".
2. **Disarm before executing.** The task leaves the armed state *before* the
   action starts. There is no moment when an already-triggered task remains
   armed.
3. **Cancel on resume.** The program subscribes to `WM_POWERBROADCAST` through
   `RegisterSuspendResumeNotification`. Any resume cancels a task that is still
   armed and reports it with a notification. After a wake-up, only the user can
   arm again.
4. **Detecting an interrupted countdown.** If two ticks of the countdown are
   separated by more than a minute, the process was frozen — the machine was
   suspended. A deadline crossed during that gap is cancelled instead of being
   played. This rule does not depend on any Windows notification: it protects
   even if the subscription fails.

A runtime precaution comes on top: before any suspend, the program waits a few
seconds without keyboard or mouse activity. On a machine whose mouse is armed
to wake it, calling `SetSuspendState` while a movement is still being processed
brings the system back out of sleep within a second.

The scheduler tests replay the sequences from the table above with a simulated
clock, without ever putting the machine to sleep.

## What the program cannot fix

Two causes of spurious wake-ups come from the machine's configuration, and no
software will fix them for you.

### Modern standby (`S0 Low Power Idle`)

```console
> powercfg /a
The following sleep states are available on this system:
    Standby (S0 Low Power Idle) Network Connected
    Hibernate
```

If `S3` is missing from this list, "sleep" does not suspend the machine: it
stays powered, the network stays connected, and the system regularly comes up
from its idle state. Fans spinning back up and lit indicators are the normal
behavior of this mode, not a malfunction.

**Remedy**: prefer `Hibernate` (S4), which really cuts the power. It is the
program's default action. You can also have Windows switch to hibernation on
its own after a period of modern standby:

```console
> powercfg /change hibernate-timeout-ac 30
```

### Devices armed to wake the machine

```console
> powercfg /devicequery wake_armed
HID-compliant mouse (004)
```

An armed mouse wakes the machine at the slightest movement — a knock on the
desk, optical sensor drift, a pet. To disarm it:

```console
> powercfg /devicedisablewake "HID-compliant mouse (004)"
```

The keyboard is then the only way to wake the PC. Two other commands are useful
for diagnosis:

```console
> powercfg /lastwake      # what woke the machine last time
> powercfg /waketimers    # active wake timers (requires elevation)
```
