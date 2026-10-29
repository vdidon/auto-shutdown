"""Checks for the reminder window.

These tests build real tkinter windows without ever showing them. They are
skipped wherever no display is available.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Iterator
from tkinter import ttk

import pytest

from auto_shutdown.config import POSTPONE_CHOICES
from auto_shutdown.power import Action
from auto_shutdown.scheduler import Snapshot, State
from auto_shutdown.ui import ReminderWindow, UiCallbacks


@pytest.fixture(scope="session")
def root() -> Iterator[tk.Tk]:
    """Single tkinter root for the whole suite.

    One root per test would fail: tkinter copes poorly with several successive
    `Tk` instances in the same process, and the error would then pass for a
    missing display.
    """
    try:
        window = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - depends on the environment
        pytest.skip(f"tkinter unavailable: {exc}")
    window.withdraw()
    yield window
    window.destroy()


@pytest.fixture
def snapshot() -> Snapshot:
    return Snapshot(
        state=State.REMINDING, action=Action.HIBERNATE, remaining=263.0, reminder_active=True
    )


class SpyCallbacks:
    """Records what the window triggers."""

    def __init__(self, snapshot: Snapshot) -> None:
        self.postponed: list[int] = []
        self.cancelled = 0
        self._snapshot = snapshot

    def as_callbacks(self) -> UiCallbacks:
        return UiCallbacks(
            on_arm=lambda *_: None,
            on_cancel=self._cancel,
            on_postpone=self.postponed.append,
            on_quit=lambda: None,
            snapshot=lambda: self._snapshot,
        )

    def _cancel(self) -> None:
        self.cancelled += 1


def buttons_of(widget: tk.Misc) -> list[ttk.Button]:
    """Recursively collects the buttons of a window."""
    found: list[ttk.Button] = []
    for child in widget.winfo_children():
        if isinstance(child, ttk.Button):
            found.append(child)
        found.extend(buttons_of(child))
    return found


def test_reminder_offers_every_postpone_choice(root: tk.Tk, snapshot: Snapshot) -> None:
    spy = SpyCallbacks(snapshot)
    window = ReminderWindow(root, spy.as_callbacks(), snapshot)
    try:
        labels = [button.cget("text") for button in buttons_of(window._win)]
        for minutes in POSTPONE_CHOICES:
            assert f"{minutes} min" in labels
        assert "Cancel" in labels
        assert "Let it run" in labels
    finally:
        window.close()


def test_each_postpone_button_sends_its_own_duration(root: tk.Tk, snapshot: Snapshot) -> None:
    """Guard against the loop-closure pitfall: each button must be distinct.

    Written without `minutes=minutes`, all four buttons would send the last
    duration of the loop.
    """
    for expected in POSTPONE_CHOICES:
        spy = SpyCallbacks(snapshot)
        window = ReminderWindow(root, spy.as_callbacks(), snapshot)
        try:
            target = next(
                button
                for button in buttons_of(window._win)
                if button.cget("text") == f"{expected} min"
            )
            target.invoke()
        finally:
            window.close()
        assert spy.postponed == [expected]


def test_cancel_button_cancels(root: tk.Tk, snapshot: Snapshot) -> None:
    spy = SpyCallbacks(snapshot)
    window = ReminderWindow(root, spy.as_callbacks(), snapshot)
    try:
        target = next(b for b in buttons_of(window._win) if b.cget("text") == "Cancel")
        target.invoke()
    finally:
        window.close()
    assert spy.cancelled == 1
    assert spy.postponed == []


def test_reminder_shows_the_countdown(root: tk.Tk, snapshot: Snapshot) -> None:
    window = ReminderWindow(root, SpyCallbacks(snapshot).as_callbacks(), snapshot)
    try:
        assert window._countdown_var.get() == "00:04:23"
    finally:
        window.close()
