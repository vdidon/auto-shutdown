"""Vérifications de la couche Win32 et du formatage des durées.

Ces tests appellent les vraies API Windows, mais aucune ne modifie l'état de la
machine : création d'une icône en mémoire et lecture du temps d'inactivité.
"""

from __future__ import annotations

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="API propres à Windows")

from auto_shutdown import winapi  # noqa: E402
from auto_shutdown.ui import format_duration  # noqa: E402


def test_make_icon_returns_a_handle() -> None:
    handle = winapi.make_icon((235, 150, 40))
    assert handle
    assert winapi.user32.DestroyIcon(handle)


@pytest.mark.parametrize("size", [16, 32, 48])
def test_make_icon_handles_usual_sizes(size: int) -> None:
    handle = winapi.make_icon((120, 140, 160), size=size)
    assert handle
    winapi.user32.DestroyIcon(handle)


def test_idle_seconds_is_a_sane_duration() -> None:
    """Le temps d'inactivité doit être positif et exempt de repliement 32 bits."""
    idle = winapi.idle_seconds()
    assert idle >= 0.0
    assert idle < 24 * 3600


def test_single_instance_mutex_is_exclusive() -> None:
    name = "Local\\AutoShutdownTestMutex"
    first = winapi.acquire_single_instance_mutex(name)
    assert first is not None
    try:
        assert winapi.acquire_single_instance_mutex(name) is None
    finally:
        winapi.kernel32.CloseHandle(first)


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "00:00:00"),
        (59.4, "00:00:59"),
        (60, "00:01:00"),
        (3661, "01:01:01"),
        (-5, "00:00:00"),
        (25 * 3600, "25:00:00"),
    ],
)
def test_format_duration(seconds: float, expected: str) -> None:
    assert format_duration(seconds) == expected
