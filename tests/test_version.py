"""Vérifie la cohérence et la forme du numéro de version.

`__version__` est la source de vérité à l'exécution : contrairement aux
métadonnées d'installation, elle reste lisible depuis un exécutable PyInstaller.
`pyproject.toml` porte nécessairement la même valeur pour la distribution ; ces
tests interdisent aux deux de diverger en silence.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import auto_shutdown

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

#: Version sémantique : MAJEUR.MINEUR.CORRECTIF, avec pré-version facultative.
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")


def declared_version() -> str:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]


def test_version_follows_semver() -> None:
    assert SEMVER.match(auto_shutdown.__version__), (
        f"{auto_shutdown.__version__!r} n'est pas une version sémantique"
    )


def test_module_and_pyproject_agree() -> None:
    """Le numéro affiché à l'utilisateur doit être celui de la distribution."""
    assert auto_shutdown.__version__ == declared_version()


def test_changelog_documents_the_current_version() -> None:
    changelog = PYPROJECT.parent / "CHANGELOG.md"
    assert changelog.is_file(), "CHANGELOG.md est absent"
    assert f"## {auto_shutdown.__version__}" in changelog.read_text(encoding="utf-8"), (
        f"la version {auto_shutdown.__version__} n'a pas d'entrée dans CHANGELOG.md"
    )
