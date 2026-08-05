"""The claim this package's index makes about its own modules, asserted against the directory.

The index says every module of the package appears in it. That is a claim about the source, so it
is read from the source in both directions: a module absent from the table fails, and a table row
naming a module that does not exist fails too. An index a reader cannot trust is worse than none,
and this one is what tells a reader of ``materialize`` where the rules, the clauses and the figures
live.

The reading is duplicated here rather than shared with the api member's equivalent, for the same
reason the boundary probe is: a member's test path resolves against its own directory, and
reaching into a sibling's test tree would be a worse coupling than a dozen lines.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import syncr_solver

COMPLETENESS_CLAIM: Final = "Every module in this package appears"

_INDEXED_MODULE = re.compile(r"``([a-z_]+\.py)``")


def index() -> str:
    return syncr_solver.__doc__ or ""


def modules_on_disk() -> set[str]:
    directory = Path(syncr_solver.__file__ or "").parent
    return {path.name for path in directory.glob("*.py") if path.name != "__init__.py"}


def test_the_index_claims_to_be_complete() -> None:
    # The claim itself, so the package cannot quietly drop the sentence and keep a stale table.
    assert COMPLETENESS_CLAIM in index()


def test_every_module_of_the_package_appears_in_the_index() -> None:
    assert set(_INDEXED_MODULE.findall(index())) == modules_on_disk()


def test_the_reading_finds_the_rows_rather_than_every_double_backtick_in_the_docstring() -> None:
    # The control for the reading above. Without it, a pattern that matched nothing would keep
    # passing after someone emptied the table.
    assert _INDEXED_MODULE.findall("| ``one.py`` | holds ``SolveInputs`` |") == ["one.py"]
    assert modules_on_disk()


def test_the_entry_point_and_the_label_its_caller_needs_are_the_package_root_s_whole_surface() -> (
    None
):
    # One entry point today and one enum, because the caller has to name which of the three causes
    # asked. `solve` is the second entry point and lands with the search phases; `derive` is not an
    # entry point, so it is imported from the module that defines it.
    assert set(syncr_solver.__all__) == {"MaterializeCause", "materialize"}
    assert all(hasattr(syncr_solver, name) for name in syncr_solver.__all__)
