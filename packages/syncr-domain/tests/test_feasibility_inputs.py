"""``ProbeInputs`` itself: what it carries, what it refuses, and what the field table claims.

Two of these are stated over the field inventory rather than over a behaviour, and that is the
point of them. This struct has needed an arithmetic correction in four consecutive reviews, each
time because a field's meaning moved elsewhere without the struct being revisited, so the module
docstring carries a row per field and these tests hold the two sets equal. A field with no row is
the failure mode the table exists to prevent.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import re
from datetime import timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from syncr_domain import feasibility
from syncr_domain.feasibility import (
    DeadlineDemand,
    FeasibilityError,
    FloorReservation,
    ProbeInputs,
    ScopedWindow,
    probe,
)
from syncr_domain.feasibility import inputs as inputs_module
from syncr_domain.intervals import Interval, IntervalError, IntervalSet
from tests.instants import at
from tests.probe_weeks import CAREER, FITNESS, NOW, STUDY, a_demand, a_week

PACKAGE_ROOT = Path(feasibility.__file__).parent

# What a row says when the definition it points at is stated in the module the table is in.
THIS_MODULE = "this module"

# A row of the field table: the field name in backticks, then the question, then the owner.
TABLE_ROW = re.compile(r"^\| `(?P<field>\w+)` \| (?P<question>[^|]+) \| (?P<owner>[^|]+) \|$")


def table_rows() -> dict[str, tuple[str, str]]:
    """The field table, parsed out of the module docstring that carries it."""
    docstring = inputs_module.__doc__ or ""
    rows: dict[str, tuple[str, str]] = {}
    for line in docstring.splitlines():
        matched = TABLE_ROW.match(line.strip())
        if matched is not None:
            rows[matched["field"]] = (matched["question"].strip(), matched["owner"].strip())
    return rows


def test_every_field_has_a_row_in_the_table_and_every_row_has_a_field() -> None:
    # An equality in both directions: a field added without a row is the drift this table exists
    # to catch, and a row left behind by a field that went away is a claim about nothing.
    assert set(table_rows()) == {field.name for field in dataclasses.fields(ProbeInputs)}


def test_every_row_answers_a_question_and_names_where_the_answer_lives() -> None:
    # The table is only a drift-catcher if every row carries both halves AND the owner it names is
    # real. Every dotted owner is resolved, in this package and in the two downstream ones, so a
    # row naming a module that does not exist fails here rather than reading as an answer.
    #
    # `find_spec` resolves without executing the module's body, and the parent packages it does
    # import carry nothing but a docstring. The domain's purity rule is about what SOURCE imports;
    # this is a test reading the tree.
    #
    # A row whose owner lives in a package that is not installed is reported as unresolved rather
    # than failing, because this suite has to run against a domain package on its own: the workspace
    # installs all six members, so in every environment that has them the guard is total.
    for field, (question, owner) in table_rows().items():
        assert "?" in question, field
        assert owner, field
        if owner == THIS_MODULE or not owner.startswith("`"):
            continue
        module = owner.strip("`")
        if not _package_is_installed(module):
            continue
        assert importlib.util.find_spec(module) is not None, owner


def test_the_guard_can_resolve_every_owner_the_table_names() -> None:
    # An inventory rather than a rule, for the same reason the assembler's read-count guard next
    # door is one: an owner the guard cannot resolve is an unchecked row, and this asserts there
    # are none. A row that named prose would have to be added to the resolvable forms above
    # deliberately, which is the moment to ask whether the thing it names has a home yet.
    #
    # It also names what the resolution costs: this suite reads two downstream packages, so it
    # reports rather than asserts when one of them is absent. Both are installed in the workspace.
    unresolvable = {
        field
        for field, (_, owner) in table_rows().items()
        if owner != THIS_MODULE and not owner.startswith("`")
    }
    absent = {
        field
        for field, (_, owner) in table_rows().items()
        if owner.startswith("`") and not _package_is_installed(owner.strip("`"))
    }

    assert unresolvable == set()
    assert absent == set(), (
        f"install the packages these rows name, or the guard skips them: {absent}"
    )


def _package_is_installed(module: str) -> bool:
    """Whether the top-level package a dotted owner names can be found at all."""
    return importlib.util.find_spec(module.split(".")[0]) is not None


def test_every_module_in_the_package_appears_in_its_index() -> None:
    # The same claim the api's package indexes carry: an index a reader cannot trust is worse
    # than none, and this one was written when the package had four modules.
    named = {
        matched.group(1) for matched in re.finditer(r"``(\w+\.py)``", feasibility.__doc__ or "")
    }

    assert named == {path.name for path in PACKAGE_ROOT.glob("*.py") if path.name != "__init__.py"}


def test_the_struct_carries_a_default_for_everything_a_week_might_not_have() -> None:
    # The reason the arithmetic is testable from literals at all: a case states the fields it is
    # about. The four without defaults are the four every week has.
    required = {
        field.name
        for field in dataclasses.fields(ProbeInputs)
        if field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING
    }

    assert required == {"span", "now", "computed_at", "input_version"}


def test_both_instants_are_normalized_so_two_readings_of_one_moment_are_equal() -> None:
    local = NOW.astimezone(ZoneInfo("Europe/London"))

    assert a_week(now=local, computed_at=local) == a_week(now=NOW, computed_at=NOW)


@pytest.mark.parametrize("field", ["now", "computed_at"])
def test_an_instant_carrying_no_zone_names_no_instant_and_is_refused(field: str) -> None:
    naive = NOW.replace(tzinfo=None)

    with pytest.raises(IntervalError):
        a_week(**{field: naive})


def test_the_windows_an_area_may_not_use_are_read_through_one_reading_of_the_scope() -> None:
    # A caller never has to decide what a scope means: it asks the struct.
    week = a_week(
        scoped_forbidden=(
            ScopedWindow(interval=at_hour(9, 11), forbidden_area_ids=(STUDY,)),
            ScopedWindow(interval=at_hour(12, 13), forbidden_area_ids=(STUDY, CAREER)),
        )
    )

    assert week.scoped_against(STUDY) == IntervalSet([at_hour(9, 11), at_hour(12, 13)])
    assert week.scoped_against(CAREER) == IntervalSet([at_hour(12, 13)])
    assert week.scoped_against(FITNESS) == IntervalSet()


def at_hour(start: int, end: int) -> Interval:
    return Interval(at(start, day=2), at(end, day=2))


def test_a_window_forbidding_nobody_is_not_a_scoped_window() -> None:
    # An empty list of Areas would have to mean either "forbids everything" or "forbids nothing",
    # and the absolute set already carries the first. So it means neither and is refused.
    with pytest.raises(FeasibilityError):
        ScopedWindow(interval=at_hour(9, 11), forbidden_area_ids=())


def test_a_reservation_of_less_than_nothing_is_refused() -> None:
    # The clamp is the producer's, and this is the half that makes it observable: an Area that
    # over-served its floor reserves zero rather than lending capacity to another Area.
    with pytest.raises(FeasibilityError):
        FloorReservation(area_id=FITNESS, reserved_minutes=-60, label="Fitness")


@pytest.mark.parametrize("label", ["", "   "])
def test_a_reservation_that_does_not_name_its_area_is_refused(label: str) -> None:
    # The probe performs no lookup, so the name it renders has to arrive with the quantity.
    with pytest.raises(FeasibilityError):
        FloorReservation(area_id=FITNESS, reserved_minutes=60, label=label)


def test_a_demand_naming_no_task_is_refused() -> None:
    # The shortfall it produces says what cannot be finished, by name, so a demand that names
    # nothing produces a refusal the user cannot read.
    with pytest.raises(FeasibilityError):
        DeadlineDemand(deadline=NOW, remaining_minutes=60, area_id=CAREER, labels=())


def test_a_demand_for_less_than_nothing_is_refused() -> None:
    with pytest.raises(FeasibilityError):
        DeadlineDemand(deadline=NOW, remaining_minutes=-1, area_id=CAREER, labels=("Leetcode",))


def test_a_demand_whose_pairs_do_not_add_to_its_total_is_refused() -> None:
    # The pairs are the tasks the total was summed over, so stating them states the same figure
    # twice. Two figures for one demand would let a stated recovery be sized against whichever
    # one the reader reached for.
    with pytest.raises(FeasibilityError):
        DeadlineDemand(
            deadline=NOW,
            remaining_minutes=90,
            area_id=CAREER,
            labels=("Leetcode", "Review"),
            contributors=((uuid4(), 60), (uuid4(), 60)),
        )


def test_a_demand_stating_pairs_that_add_up_carries_them_verbatim() -> None:
    pairs = ((uuid4(), 40), (uuid4(), 50))

    demand = DeadlineDemand(
        deadline=NOW,
        remaining_minutes=90,
        area_id=CAREER,
        labels=("Leetcode", "Review"),
        contributors=pairs,
    )

    assert demand.contributors == pairs


def test_a_demand_stating_no_pairs_is_not_refused_for_their_absence() -> None:
    # A document written before the field existed states no key for it, and a literal-stated case
    # in the probe suites names none: absence is what both of those mean, not a broken sum.
    carried = DeadlineDemand(
        deadline=NOW, remaining_minutes=60, area_id=CAREER, labels=("Leetcode",)
    )

    assert carried.contributors == ()


def test_a_demand_of_no_minutes_is_carried_and_produces_nothing() -> None:
    # Not refused: a task whose placements already cover its estimate demands zero, and the
    # producer drops it, but a zero that does reach here must not become a gap of zero minutes.
    week = a_week(deadline_demands=(a_demand(CAREER, 0, at(9, day=3)),))

    assert probe(week).shortfalls == ()


def test_a_mapping_of_targets_is_copied_so_the_caller_cannot_change_it_afterwards() -> None:
    # The struct is frozen because two probes of one assembly have to be equal. A mapping the
    # caller still holds would make that a property of the caller's discipline.
    targets = {FITNESS: 300}
    week = a_week(area_targets=targets)
    targets[FITNESS] = 999

    assert week.area_targets == {FITNESS: 300}


def test_a_week_whose_span_does_not_run_forward_is_refused_by_the_algebra() -> None:
    with pytest.raises(IntervalError):
        a_week(span=Interval(NOW, NOW - timedelta(hours=1)))


def test_the_probes_inputs_carry_no_estimate_and_no_recorded_figure() -> None:
    # The claim that a demand is not derivable here, asserted rather than stated: computing one
    # needs a task's estimate and its recorded minutes, and if either appeared on any member type
    # a later reader would derive the quantity again and the two consumers would disagree.
    carried = {
        field.name
        for member in (ProbeInputs, DeadlineDemand, FloorReservation, ScopedWindow)
        for field in dataclasses.fields(member)
    }

    assert carried & {"estimate_minutes", "recorded_minutes"} == set()
