"""What the construction and the search may read, and what the whole package may import.

Three inventories, each stated as the set of things that MAY exist rather than as a list of things
that may not. A vocabulary guard only catches the names someone thought to forbid; an inventory
guard fails on anything new.

- every field of ``SolveInputs`` the five phases read, which is the drift-catcher for the two
  quantities the solver must not confuse;
- every module the phases are made of, so a sibling's module joining the package cannot silently
  widen the inventory above;
- the seed, which nothing here reads, because the comparator breaks every tie.

Each reading carries a control, because a reading that finds nothing passes every assertion made
over it.
"""

from __future__ import annotations

import re
from typing import Final

from syncr_solver.budget import SolveBudget
from tests.test_objective_boundary import code_of, package_directory, source_of

# The modules the five phases are made of. Named rather than globbed, for the reason the objective's
# own inventory is: these are claims about THIS work.
SOLVE_MODULES: Final = (
    "solve.py",
    "candidates.py",
    "tiebreak.py",
    "attempt.py",
    "inheritance.py",
    "elastic.py",
    "offering.py",
    "binding.py",
    "filling.py",
    "moves.py",
    "search.py",
    "verdicts.py",
    "budget.py",
)

# Every field of `SolveInputs` the five phases read, and nothing else.
#
# `deadline_demands` is deliberately absent, and it is the whole point of this inventory. It is the
# PROBE's demand quantity: it nets every placement rather than the immovable ones and it is scoped
# per deadline. Read by construction, a four-hour task with two hours already placed unpinned would
# be scheduled at two hours, the next assembly would net the same two and report two again, and
# nothing would report a shortfall because both sides would agree.
#
# `for_probe` is the projection the verdict phase runs the probe over. It is how the probe's own
# demands reach a solver verdict, and it is the only route: the projection carries them verbatim,
# and no phase here reads them.
FIELDS_READ: Final = frozenset(
    {
        "adjustments",
        "eligible_tasks",
        "for_probe",
        "habit_occurrences",
        "input_version",
        "iso_week",
        "live_plan",
        "now",
        "pins",
        "preferences",
        "template_entries",
        "zone_by_date",
    }
)

_INPUTS_READ = re.compile(r"inputs\.([a-z_]+)")


def solve_source() -> str:
    """Every module of the five phases, as statements: no docstrings and no comments.

    The prose in these modules names the fields they deliberately do not read, at length. Read as
    written, every one of those sentences would fail the guard it exists to explain.
    """
    return code_of("\n".join(source_of(module) for module in SOLVE_MODULES))


def test_every_module_of_the_five_phases_is_on_disk_where_the_inventory_expects_it() -> None:
    # The control for every reading below: a mistyped module name would make each of them a claim
    # about an empty string.
    for module in SOLVE_MODULES:
        assert (package_directory() / module).is_file(), module
    assert len(solve_source()) > 10_000


def test_the_five_phases_read_exactly_the_declared_fields_of_their_inputs() -> None:
    read = set(_INPUTS_READ.findall(solve_source()))

    assert read == set(FIELDS_READ)


def test_the_probes_deadline_demand_is_read_by_no_phase_of_a_solve() -> None:
    """The AC this inventory exists for, stated on its own as well as through the set above.

    Both spellings, because a phase could have reached the quantity through the type as easily as
    through the field: the solver's demand is ``EligibleTask.remaining_minutes`` and nothing else.
    """
    source = solve_source()

    assert "deadline_demands" not in FIELDS_READ
    assert "deadline_demands" not in source
    assert "DeadlineDemand" not in source


def test_the_reading_finds_a_field_access_rather_than_matching_nothing() -> None:
    # The control for the reading itself. Without it, a pattern that matched nothing would keep
    # passing after someone added a read of every field there is.
    assert _INPUTS_READ.findall("return inputs.deadline_demands") == ["deadline_demands"]
    assert _INPUTS_READ.findall("no field access here") == []


def test_no_phase_reads_the_seed_a_tie_would_have_been_resolved_with() -> None:
    """The comparator breaks every tie, so no figure a document carries can depend on a seed.

    The stronger property rather than the weaker one: not that a particular order ignored the seed,
    but that no expression in any of the five phases can reach it.
    """
    assert "seed" not in solve_source()


def test_the_seed_exists_and_is_reachable_from_the_inputs_the_phases_hold() -> None:
    # The control for the assertion above: if the seed had been removed from `SolveInputs`, the
    # claim that nothing reads it would be true and worthless.
    from tests.solve_weeks import a_week

    assert isinstance(a_week().seed, int)


def test_no_phase_names_a_randomness_source_or_a_temperature() -> None:
    """The search accepts only strict improvements, so it needs neither.

    Stated over the source rather than over behaviour, because the absence is what makes the
    determinism property provable at all: a schedule read from a clock would pass a twice-in-one-
    process test and fail across two machines.
    """
    source = solve_source()

    for forbidden in ("random", "shuffle", "temperature", "anneal", "perf_counter", "monotonic"):
        assert forbidden not in source, forbidden


def test_the_budget_is_configured_rather_than_read_from_the_environment() -> None:
    """A caller states its budget. Read from the environment, two workers would differ."""
    assert SolveBudget().move_evaluations > 0
    assert "environ" not in solve_source()
    assert "getenv" not in solve_source()
