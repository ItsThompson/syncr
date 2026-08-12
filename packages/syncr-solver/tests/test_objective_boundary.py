"""What the objective may read, and what the package may import. Both as inventories.

Every guard here is stated as the set of things that MAY exist rather than as a list of things
that may not. A vocabulary guard only catches the names someone thought to forbid; an inventory
guard fails on anything new, which is what makes it worth trusting.

Four inventories:

- the fields of ``SolveInputs`` the objective reads, which is the drift-catcher for the two
  quantities it must not read;
- the members of the hard-constraint checker's state it reads, which is what keeps the netted set
  and the discretionary denominator from being restated here;
- every top-level module the whole package imports, which is where the zero-ML rule is decidable
  from the source rather than from the lockfile;
- and one crossing rather than an inventory: the free-time set the fragmentation term measures
  gaps over, against the figure the document reports for the same subtraction.

Each reading carries a control, because a reading that finds nothing passes every assertion made
over it. An instrument is worthless until it has been shown to fail.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import TYPE_CHECKING, Final

import syncr_solver
from syncr_domain.identity import BindingRef
from syncr_solver.figures import week_figures
from syncr_solver.reading import PlanReading
from tests.materialized_weeks import (
    FITNESS,
    a_block,
    a_frame_entry,
    a_live_plan,
    a_recovery_window,
    an_anchor,
    an_off_plan_period,
    between,
    inputs,
    on,
)
from tests.objective_weeks import A_TASK, an_eligible_task

if TYPE_CHECKING:
    from syncr_solver.inputs import SolveInputs

# The modules the objective is made of. Named rather than globbed, because the inventories below
# are claims about THIS work and a sibling's module joining the package must not silently widen
# them.
OBJECTIVE_MODULES: Final = ("objective.py", "terms.py", "preferred.py", "reading.py", "weights.py")

# Every field of `SolveInputs` the objective reads, and nothing else.
#
# `deadline_demands` is deliberately absent: it is the PROBE's demand quantity, it nets every
# placement rather than the immovable ones, and it is scoped per deadline. Read here it would
# schedule a task at half its size and report no shortfall, because both sides would agree.
#
# `live_plan` is absent too, and for the churn term that is the point: the live plan is the newest
# revision whatever its status, and churn is measured against the newest APPROVED one, which the
# baseline carries. The checker's state reads `live_plan` for the netted set, which is a different
# question about the same field.
#
# `zone_by_date` is read for the local hour a fitted curve is keyed on, and it is read from HERE
# rather than from the document's own copy of the same mapping, so the day bounds and the zone have
# one source. `span` and `iso_week` are read for the week the two must agree on.
FIELDS_READ: Final = frozenset(
    {
        "areas",
        "churn_baseline",
        "eligible_tasks",
        "habit_occurrences",
        "iso_week",
        "preferences",
        "zone_by_date",
    }
)

# Every member of `PartialPlan` the objective reads. Three, each answering a question the objective
# must not answer for itself: which bindings the producer's figures already net, what the week's
# discretionary denominator is, and which local dates it holds.
STATE_MEMBERS_READ: Final = frozenset({"already_netted", "days", "discretionary"})

# Every top-level module this package imports. The zero-ML rule, decidable from the source: an ML
# library is not on this list, and neither is anything else nobody has justified. The lockfile
# guard in `test_dependency_boundary.py` answers the other half, which is what SHIPS in an image.
IMPORTS_ALLOWED: Final = frozenset(
    {
        "__future__",
        "bisect",
        "collections",
        "dataclasses",
        # A sentinel instant for a candidate with no deadline, so the tie-break's key stays one
        # shape, and a duration a length is added to a start as. Both in `syncr_solver.tiebreak`
        # and `syncr_solver.offering`; nothing here reads a clock.
        "datetime",
        "enum",
        "hashlib",
        "itertools",
        "math",
        "prometheus_client",
        "sys",
        "syncr_common",
        "syncr_domain",
        "syncr_solver",
        # A monotonic clock, read in `syncr_solver.solve` and nowhere else, so the duration family
        # can be observed under the outcome a solve actually reached. Timing a call cannot change
        # what the call returns; `test_solve_boundary` asserts no other phase reads one.
        "time",
        "typing",
        "uuid",
    }
)

_INPUTS_READ = re.compile(r"inputs\.([a-z_]+)")
_STATE_READ = re.compile(r"state\.([a-z_]+)")


def code_of(source: str) -> str:
    """This source with every docstring and comment gone: the statements and nothing else.

    The inventories below are claims about what the code READS, and this package's prose names the
    fields it deliberately does not read, at length. Searched over the file as written, every one of
    those sentences would fail the guard it exists to explain.

    Every string-expression statement is dropped rather than only the first of each body, because
    the attribute docstrings this package uses are not docstrings to :mod:`ast` and would survive.
    Comments need no handling: parsing discards them.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        kept = [statement for statement in node.body if not _is_a_string_statement(statement)]
        node.body = kept or [ast.Pass()]
    return ast.unparse(tree)


def _is_a_string_statement(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


def package_directory() -> Path:
    return Path(syncr_solver.__file__ or "").parent


def source_of(module: str) -> str:
    return (package_directory() / module).read_text(encoding="utf-8")


def objective_source() -> str:
    return code_of("\n".join(source_of(module) for module in OBJECTIVE_MODULES))


def package_source() -> str:
    """Every module of the package, as statements. What the two package-wide guards read."""
    return code_of(
        "\n".join(
            path.read_text(encoding="utf-8") for path in sorted(package_directory().glob("*.py"))
        )
    )


def imported_roots(source: str) -> set[str]:
    """The first component of every module this source imports, however it imports it."""
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


# --------------------------------------------------------------------------------------
# What the objective reads of its inputs
# --------------------------------------------------------------------------------------


def test_every_module_of_the_objective_is_on_disk_where_the_inventories_expect_it() -> None:
    # The control for every reading below: a mistyped module name would make each of them a claim
    # about an empty string, and a docstring stripper that removed the statements too would make
    # each of them a claim about nothing at all.
    for module in OBJECTIVE_MODULES:
        assert (package_directory() / module).is_file(), module
    assert len(objective_source()) > 3_000
    assert code_of('"""a docstring"""\nx = 1') == "x = 1"
    assert "docstring" not in code_of('def f():\n    """a docstring"""\n    return 1')


def test_the_objective_reads_exactly_the_declared_fields_of_its_inputs() -> None:
    read = set(_INPUTS_READ.findall(objective_source()))

    assert read == set(FIELDS_READ)


def test_the_probes_deadline_demand_is_not_among_them() -> None:
    """Named on its own as well, because it is the field the term was most likely to reach for."""
    assert "deadline_demands" not in FIELDS_READ
    assert "deadline_demands" not in set(_INPUTS_READ.findall(objective_source()))


def test_no_area_floor_quantity_is_among_them_either() -> None:
    """A floor is H9. An objective term charging for it would price one requirement twice.

    Both quantities, because the two net different sets and reading either here would be the same
    fault: ``floor_minutes`` nets the immovable placements and ``floor_reservation_minutes`` nets
    every one.
    """
    source = objective_source()

    assert "floor_minutes" not in source
    assert "floor_reservation_minutes" not in source
    assert "placed_minutes" not in source


def test_the_reading_finds_a_field_access_rather_than_matching_nothing() -> None:
    # The control for the reading itself. Without it, a pattern that matched nothing would keep
    # passing after someone added a read of every field there is.
    assert _INPUTS_READ.findall("return inputs.deadline_demands") == ["deadline_demands"]
    assert _INPUTS_READ.findall("no field access here") == []


def test_the_objective_reads_exactly_the_declared_members_of_the_checkers_state() -> None:
    """Which keeps the netted set and the denominator from being restated in this work.

    ``already_netted`` is the one statement of the set the assembler subtracted before its figures
    arrived, and the api's own statement of it is ``plans.netting.Placement.immovable``.
    ``discretionary`` is the one the document's denominator and H9 both take. A member of either
    read directly here would be a second statement of a quantity, which is the fault class this
    epic has paid most for.
    """
    read = {member for member in _STATE_READ.findall(objective_source()) if member}

    assert read == set(STATE_MEMBERS_READ)


def test_the_state_reading_finds_a_member_rather_than_matching_nothing() -> None:
    assert _STATE_READ.findall("return state.started") == ["started"]


# --------------------------------------------------------------------------------------
# The zero-ML rule, from the source
# --------------------------------------------------------------------------------------


def test_no_module_of_the_package_imports_anything_outside_the_inventory() -> None:
    """The whole package, not only the objective: the rule is about the package.

    An import-time probe cannot express this, because one shared environment makes every member's
    dependency importable from every member. Read from the source, an ML import fails here whether
    or not it would ever execute.
    """
    every = package_source()

    assert imported_roots(every) <= set(IMPORTS_ALLOWED)


def test_no_ml_library_is_on_the_inventory() -> None:
    """Stated the other way round as well, because the two named libraries are the rule's point."""
    assert {"scipy", "sklearn", "scikit_learn", "numpy", "torch"} & set(IMPORTS_ALLOWED) == set()


def test_the_import_reading_finds_an_ml_import_when_there_is_one() -> None:
    # The control. The reading is shown to FAIL on the exact source it exists to catch, so a null
    # result from it means something.
    assert "scipy" in imported_roots("import scipy.optimize\n")
    assert "sklearn" in imported_roots("from sklearn.linear_model import Ridge\n")
    assert "scipy" in imported_roots("from scipy import stats\n")
    assert imported_roots("from syncr_domain.plan import Block\n") == {"syncr_domain"}


def test_no_duration_multiplier_is_named_anywhere_in_the_package() -> None:
    """The assembler applies it, so the objective cannot multiply a duration by it.

    Asserted over the whole package rather than over the weight set's fields, because a term could
    have reached one through any other route and the point is that no route exists.
    """
    every = package_source()

    assert "duration_multiplier" not in every


# --------------------------------------------------------------------------------------
# One crossing: the free-time set against the figure the document reports for it
# --------------------------------------------------------------------------------------


def a_week_with_something_left_out_of_the_denominator() -> SolveInputs:
    """A week holding all four subtrahends, so the crossing is over a denominator that moved."""
    return inputs(
        frame=(a_frame_entry(interval=between(23, 30)),),
        anchors=(an_anchor(interval=between(10, 11)),),
        forbidden_windows=(a_recovery_window(interval=between(11, 12)),),
        off_plan=(an_off_plan_period(interval=between(0, 6, day=6)),),
        eligible_tasks=(an_eligible_task(remaining_minutes=120),),
    )


def test_the_free_time_the_gaps_are_measured_over_is_the_documents_own_unallocated_figure() -> None:
    """Two statements of one subtraction, crossed rather than shared.

    The fragmentation term needs the SET so it can find the members too short to use; the document
    reports the TOTAL. Both are ``discretionary`` less what an Area's blocks claim, and they read
    the claimed spans through the same function, so this asserts the pair agrees on a week where
    every subtrahend is present and on a plan holding a block that carries no Area.

    **The Area filter inside that shared function is redundant, and the crossing cannot show it.**
    The only origins carrying no Area are the frame and an imported commitment, and both are already
    out of the denominator, so a claim over their spans subtracts time that had left it. Measured:
    dropping the filter reddens nothing in this member, which is an equivalence rather than a gap.
    """
    week = a_week_with_something_left_out_of_the_denominator()
    plan = a_live_plan(
        a_block(binding=BindingRef.for_task(A_TASK), interval=between(14, 15), area_id=FITNESS),
        a_block(
            binding=BindingRef.for_routine(A_TASK, on=on(0)),
            interval=between(23, 30),
            area_id=None,
            title="Sleep",
        ),
    )

    reading = PlanReading.of(plan, inputs=week)
    reported = week_figures(week, plan.blocks)

    assert reading.free.total_minutes() == reported.unallocated_minutes
    assert reading.discretionary_minutes() == reported.discretionary_minutes


def test_the_crossing_is_over_a_week_whose_denominator_is_not_the_whole_span() -> None:
    # The control for the crossing: on a week with no subtrahend the two figures would agree
    # trivially, and the assertion above would hold whatever either side computed.
    week = a_week_with_something_left_out_of_the_denominator()
    reading = PlanReading.of(a_live_plan(), inputs=week)

    assert reading.discretionary_minutes() < week.span.total_minutes()
