"""Interface translations: catalog consistency and language detection."""

from __future__ import annotations

from collections.abc import Iterator
from string import Formatter

import pytest

from auto_shutdown import i18n
from auto_shutdown.power import Action


@pytest.fixture(autouse=True)
def english() -> Iterator[None]:
    """Leave the process-wide language as the other tests expect it."""
    yield
    i18n.set_language(i18n.DEFAULT_LANGUAGE)


def placeholders(template: str) -> set[str]:
    return {field for _, field, _, _ in Formatter().parse(template) if field}


@pytest.mark.parametrize("code", sorted(set(i18n.CATALOGS) - {i18n.DEFAULT_LANGUAGE}))
def test_catalog_defines_the_same_keys_as_english(code: str) -> None:
    assert set(i18n.CATALOGS[code]) == set(i18n.CATALOGS[i18n.DEFAULT_LANGUAGE])


@pytest.mark.parametrize("code", sorted(i18n.CATALOGS))
def test_catalog_uses_the_same_placeholders_as_english(code: str) -> None:
    reference = i18n.CATALOGS[i18n.DEFAULT_LANGUAGE]
    for key, template in i18n.CATALOGS[code].items():
        assert placeholders(template) == placeholders(reference[key]), key


@pytest.mark.parametrize("action", list(Action))
def test_every_action_has_a_label(action: Action) -> None:
    for code in i18n.CATALOGS:
        assert f"action.{action.name}" in i18n.CATALOGS[code]


@pytest.mark.parametrize(
    ("preferred", "expected"),
    [
        (["fr-FR", "en-US"], "fr"),
        (["fr-CA"], "fr"),
        (["en-GB", "fr-FR"], "en"),
        (["de-DE", "fr-FR"], "fr"),
        (["de-DE", "ja-JP"], "en"),
        ([], "en"),
    ],
)
def test_detect_language_takes_the_first_supported_one(preferred: list[str], expected: str) -> None:
    assert i18n.detect_language(preferred) == expected


def test_detect_language_reads_windows() -> None:
    assert i18n.detect_language() in i18n.CATALOGS


def test_tr_follows_the_selected_language() -> None:
    i18n.set_language("fr")
    assert Action.SHUTDOWN.label == "Arrêter"
    i18n.set_language("en")
    assert Action.SHUTDOWN.label == "Shut down"


def test_tr_fills_placeholders() -> None:
    assert i18n.tr("menu.postpone_choice", minutes=15) == "15 minutes"


def test_unsupported_language_falls_back_to_english() -> None:
    i18n.set_language("xx")
    assert i18n.language() == "en"
