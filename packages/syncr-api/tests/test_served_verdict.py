"""Which verdict a read serves, over the real probe and the real assembler on fakes.

The rule these drive is the one place a packing failure can survive a read: the pending slot holds
the only persisted solver verdict, so a read that probed unconditionally would report the capacity
check forever.

**Four states, and the currency test is what separates two of them.** An empty slot, a slot at the
week's own version, a slot behind it, and a slot ahead of it. The third is what a mutation leaves
behind: the version moved, so the proposal describes an input state the week no longer holds and its
verdict is not about the week as it now stands. The fourth cannot happen through the shipped routes
and is driven anyway, because "current" is an equality rather than a comparison and a rule written
as ``>=`` would serve a verdict about inputs nobody has seen.

**The stored branch is served verbatim**, tradeoffs included and provenance included. A read that
re-enumerated over a fresh assembly would offer concessions sized against inputs the shortfalls
beside them were not computed from.

Nothing here reaches a database. The assembler is the real one over the fakes every assembly suite
uses, and the probe is the real one, so what the live branch answers is the arithmetic production
runs rather than a stub of it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from syncr_api.plans.proposals import PendingProposalRepository
from syncr_api.plans.records import PendingProposalRecord
from syncr_api.plans.served_verdicts import CurrentWeekVerdict, ServedVerdict
from syncr_api.plans.stored_verdicts import stored_verdict
from syncr_api.plans.verdicts import ProbeCaller, WeekProbe
from syncr_domain.feasibility import (
    Provenance,
    ShortfallKind,
    Tradeoff,
    Verdict,
    minimum_chunk_shortfall,
)
from syncr_domain.plan import AdjustmentKind
from syncr_domain.weeks import IsoWeek
from tests.assembly_fakes import (
    NOW,
    WEEK,
    FakeAreas,
    FakeRevisions,
    FakeSettings,
    FakeTasks,
    FakeVersions,
    a_task,
    an_area,
    an_assembler,
    at,
)

if TYPE_CHECKING:
    from decimal import Decimal

    from syncr_api.plans.assembler import WeekAssembler

# The version the week holds in these tests. A literal rather than the assembler fake's own default,
# because what is under test is a comparison between two figures and a shared constant would make an
# equality that reads either value pass.
THE_WEEKS_VERSION = 41

AN_OPERATION = uuid4()
A_DEADLINE = at(9, day=3)


class FakePendingProposals(PendingProposalRepository):
    """The slot's reader over one record, and no database."""

    def __init__(self, held: PendingProposalRecord | None = None) -> None:
        self._held = held
        self.reads = 0

    async def find(self, iso_week: IsoWeek) -> PendingProposalRecord | None:
        self.reads += 1
        return None if self._held is None or self._held.iso_week != iso_week else self._held


class RefusingAssembler:
    """An assembler that refuses to be called, so a path claiming to be cheap is stated rather
    than counted.

    The refusal IS the assertion: a path that must not assemble is better said by a collaborator
    that cannot be used than by a number a test has to remember to read.
    """

    async def assemble(self, iso_week: IsoWeek, now: datetime) -> object:
        message = f"the reader assembled {iso_week} at {now}, which this path must not do"
        raise AssertionError(message)


def a_solver_verdict(**changes: object) -> Verdict:
    """What a completed attempt proves: a packing failure no arithmetic can reach.

    ``feasible`` is false because the attempt found a gap, and ``provenance`` is solver because it
    attempted the placement. Both are what a read has to preserve.
    """
    fields: dict[str, object] = {
        "feasible": False,
        "provenance": Provenance.SOLVER,
        "computed_at": datetime(2026, 2, 11, 8, tzinfo=UTC),
        "input_version": THE_WEEKS_VERSION,
        "discretionary_minutes": 6720,
        "shortfalls": (
            minimum_chunk_shortfall(
                minutes=50,
                chunk_minutes=50,
                against=("F&F Past Papers",),
                deadline=A_DEADLINE,
            ),
        ),
        "tradeoffs": (
            Tradeoff(
                kind=AdjustmentKind.ACCEPT_PARTIAL,
                label="Accept partial delivery on F&F Past Papers",
                target_id=uuid4(),
                delta_minutes=50,
            ),
        ),
    }
    return Verdict(**{**fields, **changes})  # type: ignore[arg-type]


def a_slot(
    verdict: Verdict | None = None, *, input_version: int = THE_WEEKS_VERSION
) -> PendingProposalRecord:
    """One occupied slot, carrying the verdict the solve that filled it produced."""
    return PendingProposalRecord(
        tenant_id=uuid4(),
        iso_week=WEEK,
        document={},
        proposal_diff={},
        objective_breakdown={},
        verdict=stored_verdict(verdict or a_solver_verdict(input_version=input_version)),
        weight_set_version=1,
        input_version=input_version,
        operation_id=AN_OPERATION,
        candidate_adjustment=None,
        created_at=NOW,
    )


def an_impossible_week() -> WeekAssembler:
    """A week the probe can prove impossible: forty hours of work due Thursday morning.

    The version seam answers ``THE_WEEKS_VERSION``, which is what production gives: the assembly and
    the currency test read one row inside one transaction, so a live verdict names the version its
    caller reported. A fake answering something else would make the pair look like a defect.
    """
    career = an_area(name="Career", budget_percent=_percent(100))
    return an_assembler(
        areas=FakeAreas([career]),
        versions=FakeVersions(THE_WEEKS_VERSION),
        tasks=FakeTasks(
            [
                a_task(
                    area_id=career.id,
                    title="Kontron take-home",
                    estimate_minutes=40 * 60,
                    deadline=A_DEADLINE,
                )
            ]
        ),
    )


def _percent(whole: int) -> Decimal:
    from decimal import Decimal

    return Decimal(whole)


def a_reader(assembler: WeekAssembler | None = None) -> ServedVerdict:
    """The rule alone, over the real probe and the real assembler on fakes.

    It reads no slot and no version: both are its caller's, read once each and handed in, so this
    class cannot carry two snapshots of one week into one answer.
    """
    return ServedVerdict(
        assembler=assembler or an_impossible_week(),
        probe=WeekProbe(caller=ProbeCaller.REQUEST),
    )


# --------------------------------------------------------------------------------
# An empty slot: a live probe, and a probe verdict may not claim the week works
# --------------------------------------------------------------------------------


async def test_a_week_with_an_empty_slot_is_served_a_live_probe_verdict() -> None:
    served = await a_reader().for_week(WEEK, now=NOW, input_version=THE_WEEKS_VERSION, held=None)

    assert served.provenance is Provenance.PROBE
    assert served.input_version == THE_WEEKS_VERSION
    assert served.computed_at == NOW


async def test_the_live_branch_carries_a_tradeoff_for_each_gap_it_found() -> None:
    """A gap the user can do nothing about is a refusal with no remedy."""
    served = await a_reader().for_week(WEEK, now=NOW, input_version=THE_WEEKS_VERSION, held=None)

    assert served.shortfalls, "the fixture week proved feasible, so this asserted nothing"
    assert served.tradeoffs
    assert {gap.kind for gap in served.shortfalls} == {ShortfallKind.DEADLINE_CAPACITY}


# --------------------------------------------------------------------------------
# A current slot: the solve's own finding, verbatim
# --------------------------------------------------------------------------------


async def test_a_slot_at_the_weeks_own_version_serves_the_solves_verdict() -> None:
    """The stronger finding survives the read, which is what a served verdict is for."""
    held = a_slot()

    served = await a_reader().for_week(WEEK, now=NOW, input_version=THE_WEEKS_VERSION, held=held)

    assert served.provenance is Provenance.SOLVER
    assert {gap.kind for gap in served.shortfalls} == {ShortfallKind.MINIMUM_CHUNK_UNPLACEABLE}


async def test_the_stored_verdict_is_served_with_its_own_tradeoffs_and_instant() -> None:
    """Verbatim, so a concession offered beside a gap was sized against the inputs it names."""
    held = a_slot()
    expected = a_solver_verdict()

    served = await a_reader().for_week(WEEK, now=NOW, input_version=THE_WEEKS_VERSION, held=held)

    assert served.computed_at == expected.computed_at
    assert [one.label for one in served.tradeoffs] == [one.label for one in expected.tradeoffs]
    assert served.computed_at != NOW, "the fixture stamped the stored verdict at now"


async def test_a_feasible_solver_verdict_survives_the_read_as_feasible() -> None:
    """The claim only an attempted placement may make, which a fresh probe would erase.

    A probe verdict is refused the feasible claim at construction, so a read that probed instead
    would turn "this week works" into "capacity is sufficient" after every solve.
    """
    held = a_slot(
        a_solver_verdict(feasible=True, shortfalls=(), tradeoffs=()),
    )

    served = await a_reader().for_week(WEEK, now=NOW, input_version=THE_WEEKS_VERSION, held=held)

    assert served.feasible is True
    assert served.provenance is Provenance.SOLVER


# --------------------------------------------------------------------------------
# The currency test, in both directions
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("stale_version", [THE_WEEKS_VERSION - 1, THE_WEEKS_VERSION + 1])
async def test_a_slot_at_any_other_version_falls_back_to_a_live_probe(stale_version: int) -> None:
    """Current is an equality. A slot behind the week describes inputs the week no longer holds.

    Behind is what a mutation leaves: the version moved, so the proposal was solved against
    something else. Ahead is unreachable through the shipped routes and is driven anyway, because a
    rule written as a comparison would serve a verdict about inputs nobody has seen.
    """
    held = a_slot(input_version=stale_version)

    served = await a_reader().for_week(WEEK, now=NOW, input_version=THE_WEEKS_VERSION, held=held)

    assert served.provenance is Provenance.PROBE
    assert served.input_version == THE_WEEKS_VERSION


# --------------------------------------------------------------------------------
# CurrentWeekVerdict: the week the tenant is living in, and the plan check before the rule
# --------------------------------------------------------------------------------

# A week thirteen hours east resolves to a different ISO week from the UTC date for part of every
# day, which is what makes the home-zone reading observable rather than incidental.
AUCKLAND = "Pacific/Auckland"
LATE_UTC = datetime(2026, 2, 15, 23, 30, tzinfo=UTC)


def a_current_week_reader(
    *,
    weeks_with_a_plan: tuple[IsoWeek, ...] = (WEEK,),
    held: PendingProposalRecord | None = None,
    home_zone: str = "Europe/London",
    now: datetime = NOW,
    assembler: WeekAssembler | None = None,
) -> tuple[CurrentWeekVerdict, FakePendingProposals]:
    """The backlog's reader over fakes, handing the slot reader back so its reads can be counted."""
    proposals = FakePendingProposals(held)
    return (
        CurrentWeekVerdict(
            served=a_reader(assembler),
            revisions=FakeRevisions(weeks_with_a_plan=weeks_with_a_plan),
            proposals=proposals,
            versions=FakeVersions(THE_WEEKS_VERSION),
            settings=FakeSettings(home_zone),
            clock=lambda: now,
        ),
        proposals,
    )


async def test_a_current_week_with_no_plan_has_no_verdict_at_all() -> None:
    """A week with no plan has no verdict, so the two screens cannot disagree about it.

    The week's own read answers ``None`` for a week holding no plan, so the reader the backlog is
    wired to has to answer the same or the two screens answer different questions: a marked task
    with no verdict panel to explain it is the failure this rule exists against.
    """
    reader, _proposals = a_current_week_reader(weeks_with_a_plan=())

    assert await reader.read() is None


async def test_a_current_week_with_no_plan_costs_no_assembly() -> None:
    """The plan check is FIRST, so the cheap path is cheap.

    Driven with an assembler that raises rather than by counting a query, because a path that must
    not assemble is stated better by a collaborator that refuses than by a number.
    """
    reader, proposals = a_current_week_reader(
        weeks_with_a_plan=(), assembler=cast("WeekAssembler", RefusingAssembler())
    )

    assert await reader.read() is None
    assert proposals.reads == 0, "the slot was read on a path that already knew the answer"


async def test_a_current_week_with_a_plan_and_an_empty_slot_probes() -> None:
    reader, proposals = a_current_week_reader()

    served = await reader.read()

    assert served is not None
    assert served.provenance is Provenance.PROBE
    assert proposals.reads == 1, "the slot is read once per backlog read"


async def test_a_current_week_with_a_plan_and_a_current_slot_serves_the_solves_verdict() -> None:
    """The same rule the Week screen serves, reached through the same collaborator."""
    reader, _proposals = a_current_week_reader(held=a_slot())

    served = await reader.read()

    assert served is not None
    assert served.provenance is Provenance.SOLVER
    assert {gap.kind for gap in served.shortfalls} == {ShortfallKind.MINIMUM_CHUNK_UNPLACEABLE}


async def test_which_week_is_asked_about_is_resolved_in_the_home_zone() -> None:
    """23:30 UTC is already the next day in Auckland, and that day is in the following ISO week.

    A reader resolving the week in UTC would ask about the week this tenant has finished living in.
    The instant is fixed rather than waited for, because the two answers differ for thirteen hours a
    day and a test that only had bite during them would pass for the wrong reason the rest of the
    time.
    """
    utc_week = IsoWeek.containing(LATE_UTC.date())
    local_week = IsoWeek.containing(LATE_UTC.astimezone(ZoneInfo(AUCKLAND)).date())
    assert local_week != utc_week, "the fixture instant agrees in both zones, so this asserts none"

    east, _proposals = a_current_week_reader(
        weeks_with_a_plan=(local_week,), home_zone=AUCKLAND, now=LATE_UTC
    )
    reading_utc, _also = a_current_week_reader(
        weeks_with_a_plan=(utc_week,), home_zone=AUCKLAND, now=LATE_UTC
    )

    assert await east.read() is not None, "the week the tenant lives in has a plan and a verdict"
    assert await reading_utc.read() is None, "the UTC week is not the one this tenant is living in"
