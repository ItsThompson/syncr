"""The package index this member claims, asserted against the directory.

The api member's own suite found a package index twelve modules stale, and an index a reader cannot
trust is worse than none. Both directions: a module absent from the table sends nobody to it, and a
table naming a module nobody can open sends a reader looking for a file that is not there.

Stated over the two levels this package has. ``fitters/`` is named in the top-level index as a
directory and enumerated in its own, because a table of five parameters is what a reader of the
fitters wants and a sixth entry in the outer table would not tell them which parameter it fits.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import syncr_learning
from syncr_learning import fitters

COMPLETENESS_CLAIM: Final = "Every module in this package appears"

_INDEXED_MODULE = re.compile(r"``([a-z_]+\.py)``")
_INDEXED_DIRECTORY = re.compile(r"``([a-z_]+/)``")


def package_directory() -> Path:
    return Path(syncr_learning.__file__).resolve().parent


def modules_on_disk(directory: Path) -> set[str]:
    return {path.name for path in directory.glob("*.py") if path.name != "__init__.py"}


def indexed_modules(docstring: str) -> set[str]:
    return set(_INDEXED_MODULE.findall(docstring))


def test_the_package_states_that_its_index_is_complete() -> None:
    # The inventory below is only meaningful while the package still makes the claim. Without this,
    # deleting the sentence would leave the check enforcing something the package no longer says.
    assert COMPLETENESS_CLAIM in (syncr_learning.__doc__ or "")


def test_every_module_of_the_package_appears_in_its_index() -> None:
    assert (
        modules_on_disk(package_directory()) - indexed_modules(syncr_learning.__doc__ or "")
        == set()
    )


def test_the_index_names_no_module_the_package_does_not_hold() -> None:
    assert (
        indexed_modules(syncr_learning.__doc__ or "") - modules_on_disk(package_directory())
        == set()
    )


def test_every_subpackage_appears_in_the_index_as_a_directory() -> None:
    # A subpackage is not a module, so the module walk above cannot see one. Named separately rather
    # than folded in, because a directory in the table means "look inside" and a module means
    # "read".
    directories = {
        f"{path.name}/"
        for path in package_directory().iterdir()
        if path.is_dir() and (path / "__init__.py").exists()
    }

    assert directories == set(_INDEXED_DIRECTORY.findall(syncr_learning.__doc__ or ""))


def test_every_fitter_appears_in_the_fitters_index() -> None:
    directory = Path(fitters.__file__).resolve().parent

    assert modules_on_disk(directory) - indexed_modules(fitters.__doc__ or "") == set()


def test_the_fitters_index_names_no_fitter_the_directory_does_not_hold() -> None:
    directory = Path(fitters.__file__).resolve().parent

    assert indexed_modules(fitters.__doc__ or "") - modules_on_disk(directory) == set()


def test_the_fitters_barrel_exports_one_function_per_module() -> None:
    # The table in that module pairs a file with a parameter and a consumer. A file that exported
    # nothing would be a row nobody could act on, and an export with no file would be a name error.
    directory = Path(fitters.__file__).resolve().parent
    exported = {name for name in fitters.__all__ if name.startswith("fit_")}

    assert len(exported) == len(modules_on_disk(directory))
