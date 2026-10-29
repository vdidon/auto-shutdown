"""Checks the consistency and format of the version number.

`__version__` is the source of truth at runtime: unlike the installation
metadata, it remains readable from a PyInstaller executable. `pyproject.toml`
necessarily carries the same value for the distribution; these tests prevent
the two from silently diverging.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import auto_shutdown

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

#: Semantic version: MAJOR.MINOR.PATCH, with an optional pre-release.
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")


def declared_version() -> str:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]


def test_version_follows_semver() -> None:
    assert SEMVER.match(auto_shutdown.__version__), (
        f"{auto_shutdown.__version__!r} is not a semantic version"
    )


def test_module_and_pyproject_agree() -> None:
    """The number shown to the user must be the one of the distribution."""
    assert auto_shutdown.__version__ == declared_version()


def test_changelog_documents_the_current_version() -> None:
    changelog = PYPROJECT.parent / "CHANGELOG.md"
    assert changelog.is_file(), "CHANGELOG.md is missing"
    assert f"## {auto_shutdown.__version__}" in changelog.read_text(encoding="utf-8"), (
        f"version {auto_shutdown.__version__} has no entry in CHANGELOG.md"
    )
