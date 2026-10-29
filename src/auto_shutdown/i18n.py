"""User-interface translations, chosen from the Windows display language.

Every text shown to the user goes through `tr`. Log messages, exceptions and
command-line help stay in English: they are read by whoever diagnoses a problem,
not by the end user.

Adding a language means adding a module to `locales` with the same keys as
`locales.en`, then registering it in `CATALOGS`. A test enforces that every
catalog defines exactly the same keys with the same placeholders.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Final

from . import winapi
from .locales import en, fr

log = logging.getLogger(__name__)

DEFAULT_LANGUAGE: Final = "en"

#: Catalogs by ISO 639-1 code. English is the reference: a key missing from
#: another catalog falls back to its English text.
CATALOGS: Final[dict[str, dict[str, str]]] = {
    "en": en.MESSAGES,
    "fr": fr.MESSAGES,
}

_language = DEFAULT_LANGUAGE


def detect_language(preferred: Iterable[str] | None = None) -> str:
    """Return the first supported language among the user's display languages.

    `preferred` holds BCP 47 tags such as `fr-FR`, most preferred first; it
    defaults to what Windows reports. Only the primary subtag is compared, so
    `fr-CA` and `fr-BE` both select French.
    """
    if preferred is None:
        preferred = winapi.preferred_ui_languages()
    for tag in preferred:
        code = tag.split("-", 1)[0].lower()
        if code in CATALOGS:
            return code
    return DEFAULT_LANGUAGE


def set_language(code: str) -> None:
    """Select the catalog used by `tr`. An unsupported code selects English."""
    global _language  # noqa: PLW0603  (one process-wide setting, set at startup)
    if code not in CATALOGS:
        log.warning("Unsupported language %r, falling back to %s", code, DEFAULT_LANGUAGE)
        code = DEFAULT_LANGUAGE
    _language = code
    log.info("Interface language: %s", code)


def language() -> str:
    return _language


def tr(key: str, **values: object) -> str:
    """Translated text for `key`, with `{placeholders}` filled from `values`."""
    template = CATALOGS[_language].get(key)
    if template is None:
        template = CATALOGS[DEFAULT_LANGUAGE][key]
    return template.format(**values) if values else template
