"""Vérifications de la fenêtre de rappel.

Ces tests construisent de vraies fenêtres tkinter sans jamais les afficher. Ils
sont ignorés là où aucun affichage n'est disponible.
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
    """Racine tkinter unique pour toute la suite.

    Une racine par test échouerait : tkinter tolère mal plusieurs instances de
    `Tk` successives dans un même processus, et l'erreur se déguiserait alors en
    absence d'affichage.
    """
    try:
        window = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - dépend de l'environnement
        pytest.skip(f"tkinter indisponible : {exc}")
    window.withdraw()
    yield window
    window.destroy()


@pytest.fixture
def snapshot() -> Snapshot:
    return Snapshot(
        state=State.REMINDING, action=Action.HIBERNATE, remaining=263.0, reminder_active=True
    )


class SpyCallbacks:
    """Enregistre ce que la fenêtre déclenche."""

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
    """Collecte récursivement les boutons d'une fenêtre."""
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
        assert "Annuler" in labels
        assert "Laisser faire" in labels
    finally:
        window.close()


def test_each_postpone_button_sends_its_own_duration(root: tk.Tk, snapshot: Snapshot) -> None:
    """Garde-fou contre la fermeture de boucle : chaque bouton doit être distinct.

    Écrit sans `minutes=minutes`, les quatre boutons transmettraient tous la
    dernière durée de la boucle.
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
        target = next(b for b in buttons_of(window._win) if b.cget("text") == "Annuler")
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
