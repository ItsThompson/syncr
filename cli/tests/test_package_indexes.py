"""The claims each package's ``__init__`` docstring makes about its own modules.

Every package here states that every module of its own appears in its index, and that claim is
asserted in both directions: a module that lands and is not indexed sends nobody to it, and an index
naming a module nobody can open sends a reader looking for a file that is not there.

The claim itself is asserted too, so a package cannot quietly drop the sentence and stay in the
inventory below.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Final

import pytest

PACKAGES: Final = (
    "syncr_cli",
    "syncr_cli.auth",
    "syncr_cli.wire",
    "syncr_cli.rendering",
    "syncr_cli.commands",
)

COMPLETENESS_CLAIM: Final = "Every module in this package appears"

_INDEXED_MODULE = re.compile(r"``([a-z_]+\.py)``")

# `__main__.py` is an entry point rather than a module of the package: nothing imports it and it
# holds no subject. It is excluded from the index rather than listed with the modules that do.
_NOT_A_MODULE: Final = frozenset({"__init__.py", "__main__.py"})


def package_directory(package: str) -> Path:
    return Path(importlib.import_module(package).__file__ or "").parent


def modules_on_disk(package: str) -> set[str]:
    return {
        path.name
        for path in package_directory(package).glob("*.py")
        if path.name not in _NOT_A_MODULE
    }


def indexed_modules(package: str) -> set[str]:
    docstring = importlib.import_module(package).__doc__ or ""
    return set(_INDEXED_MODULE.findall(docstring))


@pytest.mark.parametrize("package", PACKAGES)
def test_each_package_claims_a_complete_index_where_a_reader_looks(package: str) -> None:
    assert COMPLETENESS_CLAIM in (importlib.import_module(package).__doc__ or "")


@pytest.mark.parametrize("package", PACKAGES)
def test_every_module_of_the_package_appears_in_its_index(package: str) -> None:
    assert modules_on_disk(package) - indexed_modules(package) == set()


@pytest.mark.parametrize("package", PACKAGES)
def test_the_index_names_no_module_the_package_does_not_hold(package: str) -> None:
    assert indexed_modules(package) - modules_on_disk(package) == set()


def test_the_package_docstring_states_the_ai_boundary() -> None:
    # The boundary is the reason this CLI can have an AI story with none of the correctness risk one
    # usually brings, and it belongs where someone opening the package reads it. The docstring is
    # wrapped, so the sentence is asserted against the prose rather than against the line breaks.
    prose = " ".join((importlib.import_module("syncr_cli").__doc__ or "").split())

    assert "never load-bearing for correctness" in prose
    assert "never computes a schedule" in prose
