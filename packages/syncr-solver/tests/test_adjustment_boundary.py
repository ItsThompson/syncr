"""A concession reaches the solver as a resolved input, and never as a table or a special case.

WA5: the week assembler reads approved concessions and folds them into the fields they modify, so
honoring one needs no special case here. Two halves, and both are asserted against the source
rather than trusted.

*No solver module reads the concession table.* The rows are one tenant's approved tradeoffs behind a
repository in the api package, and a solver module reaching for one would be reading state the
assembly already resolved, at a layer that performs no I/O at all.

*No solver module branches on a concession's KIND.* That is what "no special case" means. A
concession arrives already applied: the frame is shorter, the task is gone, the deadline is cleared,
the floor is lower. ``SolveInputs.adjustments`` is carried so a reason clause can cite what a week
was solved under, and folding it a second time from here would double it.

The walk reads the source as text, because the claim is about what the package is written to do
rather than about what one run happens to touch.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Final
from uuid import uuid4

import pytest

import syncr_solver
from syncr_domain.plan import AdjustmentKind
from syncr_solver.inputs import WeekAdjustment
from tests.materialized_weeks import inputs as a_week

PACKAGE_ROOT: Final = Path(syncr_solver.__file__ or "").parent
PACKAGE_PREFIX: Final = f"{syncr_solver.__name__}."

# What reading the table looks like, in the api's own names: the table, the repository, and the
# read a caller would make on it. Spelled as the api spells them, so a rename that kept the concept
# would still be caught by the repository name.
TABLE_READS: Final = ("week_adjustments", "WeekAdjustmentRepository", "adjustments.for_week")

# A branch on the vocabulary needs a member, and a member needs the dotted access. The bare type
# name is legitimate: it is the type of the field the assembly carries.
A_BRANCH_ON_THE_KIND: Final = "AdjustmentKind."


def solver_modules() -> list[Path]:
    """Every module of the package, at any depth.

    Recursive rather than one level, so a subpackage added in a later slice cannot escape either
    check below: the two guards are only as wide as this walk.
    """
    return sorted(PACKAGE_ROOT.rglob("*.py"))


def importable_modules() -> set[str]:
    """Every module the package exposes to an importer, spelled as a path relative to its root.

    A second, independent enumeration: this one asks the import machinery and the walk above asks
    the filesystem. Comparing them is what stops the two guards below going vacuous if the walk ever
    stops finding anything.

    Relative paths rather than basenames, so a module inside a future subpackage cannot satisfy the
    comparison by sharing a name with a top-level one.
    """
    return {
        f"{found.name.removeprefix(PACKAGE_PREFIX).replace('.', '/')}.py"
        for found in pkgutil.walk_packages(list(syncr_solver.__path__), PACKAGE_PREFIX)
        if not found.ispkg
    }


def test_the_walk_reads_every_module_of_the_package() -> None:
    # Bounded by the directory rather than by a list here, so a module added in a later slice is
    # covered by both checks below without anybody remembering to add it, and cross-checked against
    # the import machinery so a walk that silently found nothing cannot leave both guards vacuous.
    walked = {path.relative_to(PACKAGE_ROOT).as_posix() for path in solver_modules()}

    assert "inputs.py" in walked
    assert importable_modules() - walked == set()


@pytest.mark.parametrize("named", TABLE_READS)
def test_no_solver_module_reads_the_concession_table(named: str) -> None:
    reading = [path.name for path in solver_modules() if named in path.read_text()]

    assert reading == [], f"{reading} reads the concession table through {named!r}"


def test_no_solver_module_branches_on_a_concessions_kind() -> None:
    # The assertion behind "honoring one needs no special case in the solver". A concession arrives
    # already applied, so a module asking WHICH kind it is would be applying it a second time.
    branching = [path.name for path in solver_modules() if A_BRANCH_ON_THE_KIND in path.read_text()]

    assert branching == [], f"{branching} branches on a concession's kind"


def test_the_concession_a_week_was_solved_under_is_carried_as_a_resolved_value() -> None:
    # The positive half: the field exists, it holds pure values, and it is reachable from the inputs
    # rather than from a session. A test that only forbade the table would pass on a package that
    # had lost the field.
    #
    # Asserted by carrying one rather than by comparing an annotation: an annotation is a string
    # under `from __future__ import annotations`, so a reformat that says the same thing would fail
    # a string comparison and a change of type could pass one.
    concession = WeekAdjustment(
        adjustment_id=uuid4(), kind=AdjustmentKind.DROP_ITEM, target_id=uuid4()
    )

    carried = a_week(adjustments=(concession,))

    assert carried.adjustments == (concession,)
    assert isinstance(carried.adjustments[0], WeekAdjustment)
    assert (
        importlib.import_module(WeekAdjustment.__module__).__name__
        == "syncr_solver.resolved_content"
    )
    # And a week nobody conceded anything for carries none, so the field is not required to solve.
    assert a_week().adjustments == ()
