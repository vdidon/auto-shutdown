"""Vérifications de la configuration : bornes et tolérance aux fichiers abîmés."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_shutdown import config as config_module
from auto_shutdown.config import MAX_DELAY_MINUTES, Config
from auto_shutdown.power import Action


@pytest.fixture(autouse=True)
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirige la configuration vers un répertoire temporaire."""
    monkeypatch.setattr(config_module, "config_dir", lambda: tmp_path)
    return tmp_path


def test_defaults_are_usable() -> None:
    config = Config()
    assert Action.parse(config.action) is Action.HIBERNATE
    assert config.clamped_delay() == 30


def test_round_trip() -> None:
    Config(action="SLEEP", delay_minutes=90, reminder_minutes=10).save()
    reloaded = Config.load()
    assert reloaded.action == "SLEEP"
    assert reloaded.delay_minutes == 90
    assert reloaded.reminder_minutes == 10


def test_corrupted_file_falls_back_to_defaults(isolated_config: Path) -> None:
    """Un fichier illisible ne doit jamais empêcher l'application de démarrer."""
    (isolated_config / "config.json").write_text("{ ceci n'est pas du JSON", encoding="utf-8")
    assert Config.load().delay_minutes == 30


def test_unknown_keys_are_ignored(isolated_config: Path) -> None:
    (isolated_config / "config.json").write_text(
        json.dumps({"delay_minutes": 45, "obsolete_option": True}), encoding="utf-8"
    )
    config = Config.load()
    assert config.delay_minutes == 45
    assert not hasattr(config, "obsolete_option")


def test_non_object_json_falls_back(isolated_config: Path) -> None:
    (isolated_config / "config.json").write_text("[1, 2, 3]", encoding="utf-8")
    assert Config.load().delay_minutes == 30


@pytest.mark.parametrize(
    ("stored", "expected"),
    [(0, 1), (-5, 1), (30, 30), (MAX_DELAY_MINUTES + 1000, MAX_DELAY_MINUTES)],
)
def test_delay_is_clamped(stored: int, expected: int) -> None:
    assert Config(delay_minutes=stored).clamped_delay() == expected


def test_reminder_never_reaches_the_deadline() -> None:
    """Un rappel égal au délai ne laisserait aucun temps de réaction."""
    config = Config(delay_minutes=5, reminder_minutes=5)
    assert config.effective_reminder_minutes() == 4


def test_reminder_disabled_is_zero() -> None:
    config = Config(delay_minutes=30, reminder_minutes=5, reminder_enabled=False)
    assert config.effective_reminder_minutes() == 0


def test_unknown_action_falls_back_to_hibernate() -> None:
    assert Action.parse("PLIER_LE_LINGE") is Action.HIBERNATE


def test_suspending_actions_are_identified() -> None:
    assert Action.HIBERNATE.suspends
    assert Action.SLEEP.suspends
    assert not Action.SHUTDOWN.suspends
    assert not Action.LOCK.suspends
    assert Action.SHUTDOWN.is_terminal
    assert not Action.LOCK.is_terminal
