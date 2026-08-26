"""A day shape naming a routine, from the declaration to the block and the charge.

The frame is the authority for a routine's placement, and this suite is what that rule costs.
Five questions, each answered over a REAL assembly and the solver's real derivation rather than
over the resolution alone: how many blocks the week ends up with, at whose time, what the
denominator reads, what the entry's Area is charged, and what the assembly reports about it.

**The charge has to be read through ``materialize``, not off the resolved inputs.** A materialized
entry is an input, and an Area is charged when a block carrying it is placed. Asserting that
``inputs.areas[...].placed_minutes`` does not move over one assembly would assert nothing: that
figure reads the live plan, so it cannot move for a template entry in either direction. So the week
is derived and the document it produces is fed back as the live plan of a second assembly, which is
the path the product charges an Area through.

**Every exclusion here has a control on the other edge.** A habit-bound entry at the same wall time
in the same Area still materializes and is still charged, and a binding naming a routine this tenant
does not hold is still dropped and still counted. Without those two, a rule that excluded every
concrete entry, or one that answered a routine binding before looking the routine up, would pass
this file.
"""

from __future__ import annotations

import io
import json
from datetime import time
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest

from syncr_common.logging import configure_logging
from syncr_domain.identity import BindingKind, BindingRef
from syncr_domain.templates import BindingTarget
from syncr_solver import materialize
from syncr_solver.metrics import MaterializeCause
from tests.assembly_fakes import (
    MONDAY,
    NOW,
    WEEK,
    FakeAreas,
    FakeDayTypes,
    FakeHabits,
    FakeOffPlan,
    FakePlacements,
    FakeRoutines,
    FakeTemplates,
    FakeWeekPattern,
    a_concrete_entry,
    a_day_type,
    a_habit,
    a_routine,
    a_slot_entry,
    a_template,
    an_area,
    an_assembler,
    an_off_plan_period,
    between,
    every_day,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from syncr_api.areas.records import AreaRecord
    from syncr_api.habits.records import HabitRecord
    from syncr_api.offplan.records import OffPlanPeriodRecord
    from syncr_api.routines.records import RoutineRecord
    from syncr_api.templates.records import TemplateEntryRecord
    from syncr_domain.plan import Block, PlanDocument
    from syncr_solver.inputs import SolveInputs

# The routine's own time, and a DIFFERENT time for the entry that names it. Different on purpose:
# at the same wall time the entry's block would be refused by the occupancy rules for overlapping
# the frame, so every assertion here would pass for a reason that has nothing to do with charging.
ROUTINE_AT = time(6, 0)
ROUTINE_MINUTES = 30
ENTRY_AT = time(6, 45)
ENTRY_MINUTES = 15

UNRESOLVED_EVENT = "plans.assembly.template_entry_unresolved"


@pytest.fixture
def production_log_stream() -> Iterator[io.StringIO]:
    """Render to a captured stream in ``production`` mode, then hand the config back.

    Logging configuration is process-global, so this restores it on teardown: the suite's autouse
    fixture fails the test that leaks one rather than the tests after it.
    """
    stream = io.StringIO()
    configure_logging(environment="production", log_level="info", stream=stream)
    yield stream
    configure_logging(environment="test", log_level="info")


def a_wake_routine() -> RoutineRecord:
    """A routine short enough to leave the rest of the day free, and inelastic."""
    return a_routine(
        title="Wake",
        target_time=ROUTINE_AT,
        duration_minutes=ROUTINE_MINUTES,
        min_duration_minutes=ROUTINE_MINUTES,
        flex_band_minutes=0,
    )


def an_entry_naming(
    target: BindingTarget, entity_id: UUID, *, area_id: UUID | None = None
) -> TemplateEntryRecord:
    return a_concrete_entry(
        template_id=uuid4(),
        target=target,
        entity_id=entity_id,
        area_id=area_id,
        target_time=ENTRY_AT,
        duration_minutes=ENTRY_MINUTES,
    )


async def an_assembly(
    *,
    routine: RoutineRecord,
    area: AreaRecord,
    entries: Sequence[TemplateEntryRecord] = (),
    habits: Sequence[HabitRecord] = (),
    off_plan: Sequence[OffPlanPeriodRecord] = (),
    live_plan: PlanDocument | None = None,
) -> SolveInputs:
    """One week resolved: the routine, one Area, and a day shape holding ``entries`` every day."""
    day_type = uuid4()
    return await an_assembler(
        routines=FakeRoutines([routine]),
        week_pattern=FakeWeekPattern(every_day(day_type)),
        day_types=FakeDayTypes(a_day_type(day_type_id=day_type)),
        templates=FakeTemplates([a_template(day_type_id=day_type, entries=entries)]),
        habits=FakeHabits(habits),
        areas=FakeAreas([area]),
        off_plan=FakeOffPlan(off_plan),
        placements=FakePlacements(live_plan=live_plan),
    ).assemble(WEEK, NOW)


async def a_week(
    *,
    routine: RoutineRecord,
    area: AreaRecord,
    entries: Sequence[TemplateEntryRecord] = (),
    habits: Sequence[HabitRecord] = (),
    off_plan: Sequence[OffPlanPeriodRecord] = (),
) -> tuple[SolveInputs, PlanDocument]:
    """One week's inputs and the plan derivation determines for them.

    ``materialize`` rather than ``solve``: every block this suite counts is fixed by derivation, so
    a solve would add the objective, the search and a weight set to a question about placement.
    """
    inputs = await an_assembly(
        routine=routine, area=area, entries=entries, habits=habits, off_plan=off_plan
    )
    return inputs, materialize(inputs, cause=MaterializeCause.PHASE1)


async def charged_minutes(
    *,
    routine: RoutineRecord,
    area: AreaRecord,
    entries: Sequence[TemplateEntryRecord] = (),
    habits: Sequence[HabitRecord] = (),
) -> int:
    """What ``area`` is charged once the week this shape produces is the live plan.

    Two assemblies, because that is how the product charges an Area: the first derives the week and
    the second reads the blocks of it as placed time.
    """
    _, document = await a_week(routine=routine, area=area, entries=entries, habits=habits)
    recharged = await an_assembly(
        routine=routine, area=area, entries=entries, habits=habits, live_plan=document
    )
    return next(budget for budget in recharged.areas if budget.area_id == area.id).placed_minutes


def blocks_of(document: PlanDocument, kind: BindingKind) -> tuple[Block, ...]:
    return tuple(block for block in document.blocks if block.binding.kind is kind)


def start_times(document: PlanDocument) -> set[time]:
    return {block.interval.start.time() for block in document.blocks}


@pytest.mark.parametrize("area_on_the_entry", [True, False], ids=["an Area", "no Area"])
async def test_the_week_holds_one_block_for_the_routine_on_each_date_and_none_for_the_entry(
    area_on_the_entry: bool,
) -> None:
    # The two spans do not collide by identity -- the frame's binding is keyed by the routine and
    # the entry's by the entry -- so both would materialize and one date would hold the same
    # content twice. Asserted as an equality over the bindings rather than as a count, so a second
    # block under any identity fails here.
    area = an_area(name="Fitness")
    routine = a_wake_routine()
    entry = an_entry_naming(
        BindingTarget.ROUTINE, routine.id, area_id=area.id if area_on_the_entry else None
    )

    inputs, document = await a_week(routine=routine, area=area, entries=[entry])

    assert {block.binding for block in blocks_of(document, BindingKind.ROUTINE)} == {
        BindingRef.for_routine(routine.id, on=on) for on in WEEK.dates()
    }
    assert blocks_of(document, BindingKind.TEMPLATE_ENTRY) == ()
    assert inputs.template_entries == ()


@pytest.mark.parametrize("area_on_the_entry", [True, False], ids=["an Area", "no Area"])
async def test_the_time_the_entry_declares_places_nothing(area_on_the_entry: bool) -> None:
    # The declared wall time is not honoured, which is the half of this rule a user could disagree
    # with: 06:45 is what the author asked for and 06:00 is what the week holds.
    area = an_area(name="Fitness")
    routine = a_wake_routine()
    entry = an_entry_naming(
        BindingTarget.ROUTINE, routine.id, area_id=area.id if area_on_the_entry else None
    )

    _, document = await a_week(routine=routine, area=area, entries=[entry])

    assert start_times(document) == {ROUTINE_AT}


async def test_a_habit_bound_entry_at_the_same_time_still_materializes() -> None:
    # The control on the other edge of the exclusion. A rule that answered every concrete entry
    # with the frame, or one keyed on the entry's own Area being absent, would pass every
    # assertion above and fail here.
    area = an_area(name="Fitness")
    routine = a_wake_routine()
    habit = a_habit(area_id=area.id, title="Shower")
    entry = an_entry_naming(BindingTarget.HABIT, habit.id)

    inputs, document = await a_week(routine=routine, area=area, entries=[entry], habits=[habit])

    assert {carried.title for carried in inputs.template_entries} == {"Shower"}
    assert start_times(document) == {ROUTINE_AT, ENTRY_AT}
    assert len(blocks_of(document, BindingKind.TEMPLATE_ENTRY)) == len(WEEK.dates())


async def test_adding_the_entry_does_not_move_the_discretionary_denominator() -> None:
    # The frame already accounts for the routine's minutes, so there is nothing for the entry to
    # subtract. Both readings of the denominator are crossed: the document's own figure, and the
    # Area target the assembler derives from its own reading of the same subtraction.
    area = an_area(name="Fitness", budget_percent=Decimal(40))
    routine = a_wake_routine()
    entry = an_entry_naming(BindingTarget.ROUTINE, routine.id, area_id=area.id)

    without, plain = await a_week(routine=routine, area=area)
    with_entry, derived = await a_week(routine=routine, area=area, entries=[entry])

    assert derived.discretionary_minutes == plain.discretionary_minutes
    assert with_entry.areas[0].target_minutes == without.areas[0].target_minutes
    assert without.areas[0].target_minutes > 0
    # The figure that WOULD move if the entry placed a block, so the equality above is not read as
    # a claim that this week's arithmetic is insensitive to everything.
    assert derived.unallocated_minutes == plain.unallocated_minutes


async def test_the_area_the_entry_declares_is_charged_nothing() -> None:
    # Display metadata: the Area travels with the row and is charged for none of it. The habit case
    # is the control, and it charges the same span in the same Area.
    area = an_area(name="Fitness")
    routine = a_wake_routine()
    habit = a_habit(area_id=area.id, title="Shower")

    naming_the_routine = await charged_minutes(
        routine=routine,
        area=area,
        entries=[an_entry_naming(BindingTarget.ROUTINE, routine.id, area_id=area.id)],
    )
    naming_nothing = await charged_minutes(routine=routine, area=area)
    naming_a_habit = await charged_minutes(
        routine=routine,
        area=area,
        entries=[an_entry_naming(BindingTarget.HABIT, habit.id)],
        habits=[habit],
    )

    assert naming_the_routine == naming_nothing == 0
    assert naming_a_habit == len(WEEK.dates()) * ENTRY_MINUTES


@pytest.mark.parametrize("area_on_the_entry", [True, False], ids=["an Area", "no Area"])
async def test_the_assembly_reports_no_producer_defect_for_an_entry_the_frame_places(
    production_log_stream: io.StringIO, area_on_the_entry: bool
) -> None:
    # The drop stopped being reported, which is the line an operator was reading as a malformed row.
    # Both states of the row are driven: the one declaring no Area is the one that used to be
    # counted, and the dangling binding is what keeps the report reachable, so this assertion cannot
    # pass just as well if reporting had been deleted outright.
    area = an_area(name="Fitness")
    routine = a_wake_routine()

    await a_week(
        routine=routine,
        area=area,
        entries=[
            an_entry_naming(
                BindingTarget.ROUTINE,
                routine.id,
                area_id=area.id if area_on_the_entry else None,
            )
        ],
    )
    silent = _unresolved_events(production_log_stream)

    await a_week(
        routine=routine, area=area, entries=[an_entry_naming(BindingTarget.ROUTINE, uuid4())]
    )
    reported = _unresolved_events(production_log_stream)

    assert silent == []
    assert [event["by_cause"] for event in reported] == [
        {"content_this_tenant_does_not_have": len(WEEK.dates())}
    ]


async def test_the_routine_places_nothing_at_all_when_an_off_plan_span_covers_the_frame() -> None:
    # The residual, asserted rather than argued: an off-plan span that keeps no frame suppresses the
    # routine's own occurrence, the entry naming it is charged to a placement that does not exist,
    # and nothing states a minimum. That date holds neither block.
    area = an_area(name="Fitness")
    routine = a_wake_routine()
    entry = an_entry_naming(BindingTarget.ROUTINE, routine.id, area_id=area.id)
    over_monday_dawn = an_off_plan_period(interval=between(5, 6.25), keep_frame=False)

    _, document = await a_week(
        routine=routine, area=area, entries=[entry], off_plan=[over_monday_dawn]
    )

    assert BindingRef.for_routine(routine.id, on=MONDAY) not in {
        block.binding for block in document.blocks
    }
    assert [block.interval.start.date() for block in document.blocks].count(MONDAY) == 0
    assert len(blocks_of(document, BindingKind.ROUTINE)) == len(WEEK.dates()) - 1


async def test_a_slot_declaring_the_same_area_is_untouched() -> None:
    # The rule is stated over a concrete entry's binding, and a slot has none: it must not be
    # answered by the frame just because it sits in the same day shape.
    area = an_area(name="Fitness")
    routine = a_wake_routine()
    entries = [
        an_entry_naming(BindingTarget.ROUTINE, routine.id, area_id=area.id),
        a_slot_entry(template_id=uuid4(), area_id=area.id, target_time=time(18, 0)),
    ]

    inputs, document = await a_week(routine=routine, area=area, entries=entries)

    assert {carried.area_id for carried in inputs.template_entries} == {area.id}
    assert len(inputs.template_entries) == len(WEEK.dates())
    assert len(document.empty_slots) == len(WEEK.dates())


def _unresolved_events(stream: io.StringIO) -> list[dict[str, object]]:
    """Every entry-drop line written since this stream was last read, and nothing else."""
    lines = stream.getvalue().splitlines()
    stream.seek(0)
    stream.truncate()
    events = [json.loads(line) for line in lines if line]
    return [event for event in events if event["event"] == UNRESOLVED_EVENT]
