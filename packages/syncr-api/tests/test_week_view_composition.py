"""The week view's composition, over values rather than over a database.

Six subjects, each a pure function or a pure mapping, so every case a request cannot reach is
still driven: the eight readings, the three currency words, the three reasons a week holds no plan,
the six reason clauses on the wire, the names an empty slot's Area is resolved to, and the
response's own field set.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, get_args, get_type_hints
from uuid import uuid4

import pytest
from pydantic import BaseModel

from syncr_api.concessions.config import WEEKS_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.schemas import WireModel
from syncr_api.offplan.reading import off_plan_reading
from syncr_api.plans.clause_schemas import ClauseResponse, ReasonResponse, as_clause
from syncr_api.plans.currency import CURRENT, PLAN_CURRENCIES, SOLVING, STALE, plan_currency
from syncr_api.plans.document_schemas import PlanDocumentResponse
from syncr_api.plans.emptiness import (
    AWAITING_MAINTAINER,
    EMPTY_REASONS,
    OUTSIDE_HORIZON,
    SETUP_INCOMPLETE,
    EmptyReason,
    Horizon,
    empty_week,
)
from syncr_api.plans.errors import SlotContextRejected
from syncr_api.plans.readiness import MissingInput, PlanReadiness
from syncr_api.plans.readings import scheduled_minutes, unconfirmed_days, week_readings
from syncr_api.plans.schemas import WeekViewResponse
from syncr_api.plans.slot_contexts import slot_context
from syncr_api.plans.stored_reasons import CLAUSE_KIND
from syncr_api.solving.config import (
    FAILED,
    MATERIALIZE,
    PENDING,
    RUNNING,
    SOLVE,
    SUCCEEDED,
    SUPERSEDED,
)
from syncr_api.solving.records import OperationRecord
from syncr_domain.budgets import BudgetReport
from syncr_domain.gaps import SlotContext
from syncr_domain.intervals import Interval, IntervalSet
from syncr_domain.plan import PlanDocument
from syncr_domain.reasons import (
    Blocked,
    Bound,
    ChurnBaseline,
    DerivationSource,
    Dominant,
    Floor,
    InsteadOf,
    Pinned,
    ReasonRecord,
)
from syncr_domain.weeks import IsoWeek, active_zone_by_date, local_days, week_span
from syncr_domain.zones import ZoneProfile
from tests.boundaries import api_routes
from tests.plan_documents import (
    AREA_NAMES,
    CAREER,
    FITNESS,
    LONDON,
    WEEK,
    a_block,
    a_document,
    a_slot,
    a_zone_map,
    at,
    between,
)

if TYPE_CHECKING:
    from syncr_api.core.settings import ServiceSettings
    from syncr_api.solving.config import OperationKind, OperationStatus
    from syncr_domain.identifiers import AreaId

# Monday of 2026-W07 in London, where local midnight and UTC midnight coincide.
MONDAY = datetime(2026, 2, 9, tzinfo=UTC)
NEXT_MONDAY = MONDAY + timedelta(days=7)
WEEK_SPAN = Interval(MONDAY, NEXT_MONDAY)

# Havana's spring-forward transition is at local midnight, so the Sunday of this week has no 00:00
# at all and is 23 hours long. It is the one shape a per-day figure cannot get right by dividing.
HAVANA = "America/Havana"
HAVANA_TRANSITION_WEEK = IsoWeek(2026, 10)

AN_EMPTY_REPORT = BudgetReport(
    discretionary_minutes=0, allocations=(), unallocated_minutes=0, oversubscription_minutes=0
)


def a_report(**overrides: int) -> BudgetReport:
    """A budget report carrying figures, which is all the readings read off one.

    Every figure differs from the same figure on ``a_document``, so a reading taken from the wrong
    one of the two is visible: the document's three are as of the instant it was produced and the
    report's are live, and a fixture that gave them one value could not tell them apart.
    """
    fields: dict[str, int] = {
        "discretionary_minutes": 5400,
        "unallocated_minutes": 1200,
        "oversubscription_minutes": 90,
    }
    return BudgetReport(allocations=(), **(fields | overrides))


def an_operation(
    kind: OperationKind = SOLVE, status: OperationStatus = PENDING, **overrides: object
) -> OperationRecord:
    """One operation row, reduced to what the currency derivation reads."""
    fields: dict[str, object] = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "kind": kind,
        "status": status,
        "iso_week": WEEK,
        "source_id": None,
        "input_version": None,
        "candidate_adjustment": None,
        "scheduled_for": MONDAY,
        "started_at": None,
        "finished_at": None,
        "result_revision_id": None,
        "superseded_by": None,
        "attempt": 1,
        "error_code": None,
        "error_message": None,
    }
    return OperationRecord(**(fields | overrides))  # type: ignore[arg-type]


def a_horizon(days: int = 14, *, today: object = None) -> Horizon:
    """The horizon a tenant in London has on the Monday of 2026-W07."""
    return Horizon.of(today=today or MONDAY.date(), days=days)  # type: ignore[arg-type]


# --------------------------------------------------------------------------------
# scheduled_minutes: a coverage figure, unioned and clipped
# --------------------------------------------------------------------------------


def test_two_blocks_over_one_hour_schedule_that_hour_once() -> None:
    """A minute the user deliberately double-booked is one scheduled minute, not two."""
    document = a_document(
        blocks=(
            a_block(interval=between(9, 10)),
            a_block(interval=between(9, 10), binding=a_block().binding, title="second"),
        )
    )

    assert scheduled_minutes(document, WEEK_SPAN) == 60


def test_a_block_running_past_the_week_is_charged_only_for_the_part_inside_it() -> None:
    """Sunday's 23:00 sleep runs into next Monday, and next week is where those minutes belong."""
    overhanging = a_block(interval=Interval(at(23, day=6), at(31, day=6)))

    assert scheduled_minutes(a_document(blocks=(overhanging,)), WEEK_SPAN) == 60


def test_a_week_holding_nothing_schedules_nothing() -> None:
    assert scheduled_minutes(a_document(blocks=()), WEEK_SPAN) == 0


# --------------------------------------------------------------------------------
# unconfirmed_days: what a person can actually be asked to confirm
# --------------------------------------------------------------------------------


def a_week_of_blocks() -> PlanDocument:
    """One block on each of the week's seven days, so every day has something to confirm."""
    return a_document(
        blocks=tuple(
            a_block(interval=between(9, 10, day=day), binding=a_block(week=WEEK).binding)
            for day in range(7)
        )
    )


def test_every_ended_day_holding_a_block_is_unconfirmed_when_nothing_is_confirmed() -> None:
    document = a_week_of_blocks()

    counted = unconfirmed_days(document, span=WEEK_SPAN, confirmed=(), now=NEXT_MONDAY)

    assert counted == 7


def test_a_day_still_running_is_not_counted_because_it_cannot_be_confirmed_yet() -> None:
    """Wednesday noon: Monday and Tuesday have ended, and Wednesday has not."""
    document = a_week_of_blocks()

    counted = unconfirmed_days(document, span=WEEK_SPAN, confirmed=(), now=at(12, day=2))

    assert counted == 2


def test_a_confirmed_day_is_not_counted() -> None:
    document = a_week_of_blocks()

    counted = unconfirmed_days(
        document, span=WEEK_SPAN, confirmed=WEEK.dates()[:3], now=NEXT_MONDAY
    )

    assert counted == 4


def test_a_day_holding_no_block_has_nothing_to_confirm() -> None:
    """A week planned only on Monday owes one confirmation, not seven."""
    document = a_document(blocks=(a_block(interval=between(9, 10, day=0)),))

    counted = unconfirmed_days(document, span=WEEK_SPAN, confirmed=(), now=NEXT_MONDAY)

    assert counted == 1


def test_a_day_whose_own_midnight_is_in_a_daylight_saving_gap_is_still_one_day() -> None:
    """Havana's Sunday has no 00:00, so it is 23 hours long and its blocks still belong to it.

    A per-day figure taken over a 24-hour slice of the span would charge Sunday's block to Monday
    of the following week, which is a day this document does not describe at all.
    """
    week = HAVANA_TRANSITION_WEEK
    profile = ZoneProfile(home_zone=HAVANA, travel_overrides=())
    span = week_span(week, profile)
    zones = active_zone_by_date(week, profile)
    days = local_days(week, zones, span)
    sunday = days[-1]
    assert sunday.interval.total_minutes() == 23 * 60, "the fixture is not the transition week"

    document = a_document(
        week=week,
        zone_by_date=zones,
        blocks=(
            a_block(
                week=week, interval=Interval(sunday.interval.start, sunday.interval.start + HOUR)
            ),
        ),
    )

    assert unconfirmed_days(document, span=span, confirmed=(), now=span.end) == 1
    assert unconfirmed_days(document, span=span, confirmed=(sunday.on,), now=span.end) == 0


HOUR = timedelta(hours=1)


# --------------------------------------------------------------------------------
# The readings as a whole
# --------------------------------------------------------------------------------


def test_the_three_strip_figures_are_the_budget_reports_own() -> None:
    """The strip divides the denominator the pie review divides, from one arithmetic."""
    report = a_report()
    document = a_document()
    assert document.discretionary_minutes != report.discretionary_minutes, (
        "the fixtures agree, so this could not tell the two readings apart"
    )

    readings = week_readings(
        document,
        span=WEEK_SPAN,
        report=report,
        off_plan=off_plan_reading(WEEK_SPAN, IntervalSet()),
        confirmed=(),
        now=MONDAY,
        currency=CURRENT,
    )

    assert readings.discretionary_minutes == report.discretionary_minutes
    assert readings.unallocated_minutes == report.unallocated_minutes
    assert readings.oversubscription_minutes == report.oversubscription_minutes


def test_the_block_count_is_the_documents_own_and_the_currency_is_carried_through() -> None:
    document = a_document(blocks=(a_block(), a_block(interval=between(11, 12), title="second")))

    readings = week_readings(
        document,
        span=WEEK_SPAN,
        report=AN_EMPTY_REPORT,
        off_plan=off_plan_reading(WEEK_SPAN, IntervalSet([WEEK_SPAN])),
        confirmed=(),
        now=MONDAY,
        currency=STALE,
    )

    assert readings.block_count == 2
    assert readings.plan_currency == STALE
    assert readings.off_plan_minutes == WEEK_SPAN.total_minutes()


# --------------------------------------------------------------------------------
# plan_currency
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [PENDING, RUNNING])
def test_a_plan_operation_in_flight_reads_as_solving(status: OperationStatus) -> None:
    in_flight = an_operation(status=status)

    assert plan_currency(in_flight=in_flight, latest=in_flight) == SOLVING


def test_a_terminally_failed_last_operation_reads_as_stale() -> None:
    assert plan_currency(in_flight=None, latest=an_operation(status=FAILED)) == STALE


@pytest.mark.parametrize("status", [SUCCEEDED, SUPERSEDED])
def test_a_week_whose_last_operation_settled_reads_as_current(status: OperationStatus) -> None:
    assert plan_currency(in_flight=None, latest=an_operation(status=status)) == CURRENT


def test_a_week_no_operation_has_touched_reads_as_current() -> None:
    """A week planned before operations were tracked, or one materialized in one transaction."""
    assert plan_currency(in_flight=None, latest=None) == CURRENT


def test_a_retry_in_flight_after_a_failure_reads_as_solving_rather_than_stale() -> None:
    """A failure with an attempt left returns to the queue in the same transaction that wrote it.

    So a row observed as failed has no attempt left, and a pending row beside a failed one means the
    plan is being recomputed rather than that it is the last one that worked. The two arguments are
    different rows here, because the newest of the two is the one that failed: a solve due before a
    materialize that failed after it is exactly the state the order of these two branches decides.
    """
    retrying = an_operation(status=PENDING, attempt=2, error_code="solver_raised")
    failed_later = an_operation(
        kind=MATERIALIZE, status=FAILED, scheduled_for=MONDAY + timedelta(minutes=1)
    )

    assert plan_currency(in_flight=retrying, latest=failed_later) == SOLVING


def test_a_materialize_counts_as_a_plan_operation() -> None:
    """The maintainer produces a plan with a materialize, and that changes the block count."""
    assert plan_currency(in_flight=an_operation(kind=MATERIALIZE), latest=None) == SOLVING


def test_the_three_words_are_the_whole_vocabulary() -> None:
    assert set(PLAN_CURRENCIES) == {CURRENT, SOLVING, STALE}
    assert len(PLAN_CURRENCIES) == 3


# --------------------------------------------------------------------------------
# Why a week holds no plan
# --------------------------------------------------------------------------------

# The horizon every case below is asked against, and the two weeks either side of it.
_HORIZON = a_horizon()
_INSIDE = WEEK
_BEYOND = IsoWeek(2027, 3)

_NOTHING_DECLARED = PlanReadiness((MissingInput.AREAS, MissingInput.DAY_SHAPE))
_NO_AREAS = PlanReadiness((MissingInput.AREAS,))
_READY = PlanReadiness()


@pytest.mark.parametrize(
    ("iso_week", "readiness", "reason", "missing", "stated", "covered"),
    [
        pytest.param(
            _INSIDE,
            _NOTHING_DECLARED,
            SETUP_INCOMPLETE,
            (MissingInput.AREAS, MissingInput.DAY_SHAPE),
            (_NOTHING_DECLARED.statement(),),
            True,
            id="setup-incomplete-inside-the-horizon",
        ),
        # A tenant with no Areas cannot plan any week, so naming the horizon here would offer two
        # dead ends: extending it plans nothing without Areas, and solving the week is refused
        # naming the very input the screen did not mention.
        pytest.param(
            _BEYOND,
            _NO_AREAS,
            SETUP_INCOMPLETE,
            (MissingInput.AREAS,),
            (_NO_AREAS.statement(),),
            False,
            id="setup-incomplete-outranks-the-horizon",
        ),
        pytest.param(
            _BEYOND,
            _READY,
            OUTSIDE_HORIZON,
            (),
            (f"{_HORIZON.days}-day", str(_HORIZON.through), "solve this week now"),
            False,
            id="beyond-the-horizon",
        ),
        pytest.param(
            _INSIDE,
            _READY,
            AWAITING_MAINTAINER,
            (),
            ("inside your", "has not been produced yet", "solve this week now"),
            True,
            id="awaiting-the-maintainer",
        ),
    ],
)
def test_every_state_a_planless_week_is_in_answers_with_its_own_word(
    iso_week: IsoWeek,
    readiness: PlanReadiness,
    reason: EmptyReason,
    missing: tuple[MissingInput, ...],
    stated: tuple[str, ...],
    covered: bool,
) -> None:
    """Three states over four cases, each asserting the word, the sentence and the flag together.

    A case that asserted the word alone would pass against a response whose sentence and flag
    contradict it, and a week the horizon holds is exactly where the three can disagree: the flag
    says the week is inside the horizon while a word borrowed from the state beyond it offers to
    extend one that already reaches the week.
    """
    assert _HORIZON.covers(iso_week) is covered, "this case names a week on the other side"

    empty = empty_week(iso_week, readiness=readiness, horizon=_HORIZON)

    assert empty.reason == reason
    assert empty.missing == missing
    assert empty.covers_this_week is covered
    for phrase in stated:
        assert phrase in empty.statement


def test_the_reasons_the_tuple_holds_are_the_reasons_the_type_names() -> None:
    """Crossed against the type rather than against a third copy of the same list.

    ``EMPTY_REASONS`` has no production reader, so a member added to ``EmptyReason`` and not to the
    tuple reaches the generated contract with mypy green and nothing else able to notice. Asserting
    the tuple against three named constants cannot see that direction: it is satisfied by editing
    the list it checks.
    """
    assert set(get_args(EmptyReason.__value__)) == set(EMPTY_REASONS)
    assert len(EMPTY_REASONS) == len(set(EMPTY_REASONS))
    assert {OUTSIDE_HORIZON, SETUP_INCOMPLETE, AWAITING_MAINTAINER} <= set(EMPTY_REASONS)


# --------------------------------------------------------------------------------
# The horizon this route compares a week against is the maintainer's own
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("days", [1, 7, 14, 15, 60])
def test_the_horizon_reaches_the_last_date_it_covers_and_no_further(days: int) -> None:
    horizon = Horizon.of(today=MONDAY.date(), days=days)

    assert horizon.through == MONDAY.date() + timedelta(days=days - 1)
    assert horizon.covers(IsoWeek.containing(horizon.through))
    assert not horizon.covers(IsoWeek.containing(horizon.through + timedelta(days=7)))


def test_every_week_the_horizon_names_holds_one_of_its_dates() -> None:
    """The same equivalence the maintainer's own suite asserts, over the value this route holds."""
    horizon = Horizon.of(today=MONDAY.date(), days=14)
    covered = {MONDAY.date() + timedelta(days=offset) for offset in range(14)}

    for week in horizon.weeks:
        assert covered & set(week.dates()), week
    for day in covered:
        assert IsoWeek.containing(day) in horizon.weeks, day


def test_a_year_boundary_week_is_inside_a_horizon_that_reaches_it() -> None:
    """2026 holds 53 ISO weeks, and the last of them holds three dates in 2027."""
    horizon = Horizon.of(today=datetime(2026, 12, 28, tzinfo=UTC).date(), days=14)

    assert IsoWeek(2026, 53) in horizon.weeks
    assert IsoWeek(2027, 1) in horizon.weeks


# --------------------------------------------------------------------------------
# The six reason clauses on the wire
# --------------------------------------------------------------------------------

A_WINDOW = between(9, 10)

A_BASELINE = ChurnBaseline(revision_id=uuid4(), approved_at=MONDAY)

EVERY_CLAUSE = (
    Blocked(window=A_WINDOW, rule="anchor_overlap", detail="Kontron Interview"),
    Dominant(term="churn", share=0.4, baseline=A_BASELINE),
    Bound(source=DerivationSource.ROUTINE, selected="Sleep · 23:00 + 8h", cursor=None),
    Floor(area_id=CAREER, floor_minutes=300, placed=3, of=4),
    Pinned(at=A_WINDOW, pinned_on=MONDAY.date()),
    InsteadOf(placement=A_WINDOW, objective_delta=1.25),
)


def test_the_wire_kinds_are_exactly_the_clause_kinds_the_domain_may_hold() -> None:
    """Bounded by the domain's own budget table rather than by a list here.

    A seventh clause kind reaching the domain has no shape on the wire until one is given, and a
    shape here that names a kind the domain does not hold renders a template for nothing.
    """
    declared = {get_args(member.model_fields["kind"].annotation)[0] for member in _wire_clauses()}

    assert declared == set(CLAUSE_KIND.values())


def _wire_clauses() -> tuple[type[BaseModel], ...]:
    """Every member of the discriminated union, read off the union itself."""
    union, _discriminator = get_args(ClauseResponse.__value__)
    members: tuple[type[BaseModel], ...] = get_args(union)
    return members


def test_every_clause_the_domain_can_hold_maps_onto_the_wire() -> None:
    for clause in EVERY_CLAUSE:
        assert as_clause(clause) is not None, clause
    assert len(EVERY_CLAUSE) == len(CLAUSE_KIND)


def test_a_clause_reaches_the_wire_with_its_own_values() -> None:
    rendered = ReasonResponse.of(ReasonRecord(EVERY_CLAUSE)).model_dump(by_alias=True)
    by_kind = {clause["kind"]: clause for clause in rendered["clauses"]}

    assert by_kind["blocked"]["rule"] == "anchor_overlap"
    assert by_kind["blocked"]["window"] == {"start": A_WINDOW.start, "end": A_WINDOW.end}
    assert by_kind["dominant"]["share"] == pytest.approx(0.4)
    assert by_kind["dominant"]["baseline"]["approvedAt"] == MONDAY
    assert by_kind["bound"]["source"] == DerivationSource.ROUTINE
    assert by_kind["floor"] == {
        "kind": "floor",
        "areaId": CAREER,
        "floorMinutes": 300,
        "placed": 3,
        "of": 4,
    }
    assert by_kind["pinned"]["pinnedOn"] == MONDAY.date()
    assert by_kind["instead_of"]["objectiveDelta"] == pytest.approx(1.25)


# --------------------------------------------------------------------------------
# The document on the wire
# --------------------------------------------------------------------------------

# The document's own three minute figures, which the wire deliberately does not carry: each was
# computed when the plan was produced, and `readings` carries all three live.
STALE_BY_NATURE = frozenset(
    {"discretionary_minutes", "unallocated_minutes", "oversubscription_minutes"}
)


def test_the_wire_document_carries_every_field_of_the_value_except_the_three_stated_ones() -> None:
    """Bounded by the domain value's own field set, so a field added there is either on the wire or
    named here as one of the three a live reading replaces."""
    fields = set(PlanDocument.__dataclass_fields__)
    on_the_wire = set(PlanDocumentResponse.model_fields)

    assert fields - on_the_wire == STALE_BY_NATURE
    assert on_the_wire - fields == set()


def test_a_documents_zones_reach_the_wire_in_date_order_whatever_order_they_arrived_in() -> None:
    """Two reads of one week are byte-identical, down to the order the mapping's keys are in."""
    reversed_zones = dict(reversed(list(a_zone_map().items())))

    rendered = PlanDocumentResponse.of(
        a_document(zone_by_date=reversed_zones), area_names=AREA_NAMES
    )

    assert list(rendered.zone_by_date) == [day.isoformat() for day in WEEK.dates()]
    assert set(rendered.zone_by_date.values()) == {LONDON}


def test_a_blocks_derived_identity_origin_and_chunk_reach_the_wire() -> None:
    """None has a field on the value, and all three are what a client pairs a selection on."""
    document = a_document()
    block = document.blocks[0]

    rendered = PlanDocumentResponse.of(document, area_names=AREA_NAMES).blocks[0]

    assert rendered.id == block.id
    assert rendered.origin == block.origin
    assert rendered.binding.split_index == block.binding.split_index


# --------------------------------------------------------------------------------
# The name an empty slot's Area is resolved to
# --------------------------------------------------------------------------------


def a_document_holding_two_slots() -> PlanDocument:
    """A week leaving two evenings unfilled, one per Area, so a resolution can be wrong per slot."""
    return a_document(
        empty_slots=(
            a_slot(area_id=CAREER, interval=between(19, 20)),
            a_slot(area_id=FITNESS, interval=between(20, 21)),
        )
    )


def test_a_slot_resolves_the_name_of_the_area_it_is_charged_to() -> None:
    """The one thing a gap's own wording needs and a stored plan does not carry.

    Compared as a whole value rather than field by field, so the period's label is pinned as
    unnamed by this resolution: which declared period a slot borrows a word from is a question
    about periods and is decided where they are read.
    """
    assert slot_context(a_slot(area_id=FITNESS), AREA_NAMES) == SlotContext(area_name="Fitness")


def test_the_document_renders_one_response_slot_per_document_slot_in_order() -> None:
    """The pairing alone. Which name each slot resolved its own Area to is the case below."""
    rendered = PlanDocumentResponse.of(a_document_holding_two_slots(), area_names=AREA_NAMES)

    assert [one.area_id for one in rendered.empty_slots] == [CAREER, FITNESS]


@pytest.mark.parametrize(
    ("named", "unnamed"),
    [
        pytest.param(FITNESS, CAREER, id="the-first-slots-area-is-the-unnamed-one"),
        pytest.param(CAREER, FITNESS, id="the-second-slots-area-is-the-unnamed-one"),
    ],
)
def test_a_slot_charged_to_an_area_the_read_did_not_name_is_refused_rather_than_answered(
    named: AreaId, unnamed: AreaId
) -> None:
    """Driven at both slot positions, which is what establishes that every slot resolves its own.

    A resolution that stopped after the first slot, or that reused the first slot's context for the
    rest, passes one of these parameters and fails the other. Either case alone could not tell those
    apart from a resolution that ran per slot.

    A refusal rather than a blank: a document and the Areas beside it come from one transaction over
    a table no route removes a row from, so the two failing to cover each other is a defect in what
    the response was composed from rather than a gap a person could read past.
    """
    with pytest.raises(SlotContextRejected, match=str(unnamed)):
        PlanDocumentResponse.of(
            a_document_holding_two_slots(), area_names={named: AREA_NAMES[named]}
        )


# --------------------------------------------------------------------------------
# The response's own field set
# --------------------------------------------------------------------------------

# The `WeekView` interface, field for field, in the api's own camelCase spelling. The
# generated `schema.d.ts` needs no hand-written companion type, which is what this pins.
SECTION_13_FIELDS = frozenset(
    {
        "isoWeek",
        "span",
        "zoneByDate",
        "live",
        "emptyReason",
        "proposal",
        "candidateAdjustment",
        "adjustments",
        "pins",
        "conflicts",
        "offPlan",
        "verdict",
        "operation",
        "inputVersion",
        "readings",
    }
)

# The one field beyond that interface, and why it has to exist: the interface has nowhere to say
# WHICH input is missing or how long the horizon is, and both are required of this response.
BEYOND_THE_INTERFACE = frozenset({"emptyWeek"})

# The `readings` block, field for field.
SECTION_13_READINGS = frozenset(
    {
        "scheduledMinutes",
        "discretionaryMinutes",
        "unallocatedMinutes",
        "oversubscriptionMinutes",
        "unconfirmedDays",
        "offPlanMinutes",
        "blockCount",
        "planCurrency",
    }
)


def aliases(model: type[BaseModel]) -> frozenset[str]:
    """The wire spelling of every field of a response model."""
    return frozenset(field.alias or name for name, field in model.model_fields.items())


def optional_fields(model: type[BaseModel]) -> frozenset[str]:
    """The fields a client would have to narrow ``undefined`` on, in their wire spelling.

    A field with a default is not required, and the generated document leaves it out of the
    ``required`` list, which openapi-typescript emits as ``field?:``. Every field of this response
    is declared required and the nullable ones nullable, which is also what thirty-six
    other response fields in this api do, so the set below is asserted to be empty rather than
    merely small.
    """
    declared = model.model_fields.items()
    return frozenset(field.alias or name for name, field in declared if not field.is_required())


def test_the_week_view_matches_section_13_field_for_field() -> None:
    assert aliases(WeekViewResponse) == SECTION_13_FIELDS | BEYOND_THE_INTERFACE


def test_the_readings_block_matches_section_13_field_for_field() -> None:
    readings = WeekViewResponse.model_fields["readings"].annotation
    assert readings is not None
    on_the_wire = aliases(get_args(readings)[0])

    assert on_the_wire == SECTION_13_READINGS


# Every wire shape a week route answers with, and every shape reachable from one, discovered by
# walking the app's own routes rather than a list of modules. A module list covered the three plan
# modules and could not see the concession, pin, conflict, off-plan or operation shapes the composed
# read nests, four of which arrived on it in one commit.

# The one exemption, and it is a field rather than a module: each clause shape's ``kind`` carries
# the union's discriminator and is set by the class, so it is not a field a client narrows.
# openapi-typescript emits a discriminated union's discriminator as required whatever its default,
# and the shapes are asserted below to declare one. Applied to the clause shapes alone, so a
# ``kind`` elsewhere is not swept up.
DISCRIMINATOR = "kind"


def nested_models(model: type[BaseModel]) -> set[type[BaseModel]]:
    """Every wire shape this one's fields can hold, at any depth of a union or a container."""
    found: set[type[BaseModel]] = set()
    for field in model.model_fields.values():
        pending: list[object] = [field.annotation]
        while pending:
            candidate = pending.pop()
            if isinstance(candidate, type) and issubclass(candidate, BaseModel):
                found.add(candidate)
            pending.extend(get_args(candidate))
    return found


def response_models(settings: ServiceSettings) -> list[type[BaseModel]]:
    """Every wire shape a week route answers with or nests, in a stable order.

    Bounded by the routes the application declares under the week prefix, so a route added to that
    prefix and a shape nested inside one come under the rule below without this test being extended.
    """
    reached: set[type[BaseModel]] = set()
    pending = [
        answered
        for route in api_routes(create_app(settings))
        if route.path.startswith(WEEKS_PREFIX)
        and isinstance(answered := get_type_hints(route.endpoint).get("return"), type)
        and issubclass(answered, BaseModel)
    ]
    while pending:
        model = pending.pop()
        if model in reached:
            continue
        reached.add(model)
        pending.extend(nested_models(model))
    return sorted(reached, key=lambda model: (model.__module__, model.__name__))


def _exempt_fields(model: type[BaseModel]) -> frozenset[str]:
    """The fields this model's optionality is not measured over."""
    return frozenset({DISCRIMINATOR}) if model in _wire_clauses() else frozenset()


def test_no_field_of_a_week_response_is_optional_in_the_generated_contract(
    settings: ServiceSettings,
) -> None:
    """A name-only assertion would not see an optionality drift, and twelve fields drifted once.

    The names are pinned above and this pins the other half of the same contract: a field that gains
    a default becomes ``field?:`` in the generated TypeScript, and a client narrowing ``null`` alone
    stops being sound against its own types while every runtime payload still carries the key.

    Stated over the shapes the composed read really nests rather than over three modules, because
    the six fields that were empty placeholders now carry a concession, a pin, a conflict, a
    proposal, a verdict and an operation, and five of those shapes are declared in another package.
    """
    models = response_models(settings)
    assert len(models) > len(SECTION_13_READINGS), "the route walk found almost nothing"

    optional = {
        f"{model.__module__}.{model.__name__}": sorted(
            optional_fields(model) - _exempt_fields(model)
        )
        for model in models
    }

    assert {name: fields for name, fields in optional.items() if fields} == {}


def test_the_route_walk_reaches_the_shapes_another_package_declares(
    settings: ServiceSettings,
) -> None:
    """The control on the walk: a module-listing version of it saw none of these.

    Five of the composed read's sixteen fields carry a shape from another feature package, and each
    is what the rule above exists to measure. A walk that reached only the plan package's own
    modules would pass while four of the five drifted.

    ``OperationTarget`` is named for a second reason: it is reached only through another response
    shape's field, so a walk that stopped one nesting short would leave its two members unmeasured
    while every other assertion in this module stayed green.
    """
    reached = {f"{model.__module__}.{model.__name__}" for model in response_models(settings)}

    assert {
        "syncr_api.concessions.schemas.AdjustmentResponse",
        "syncr_api.conflicts.schemas.ConflictResponse",
        "syncr_api.pins.schemas.PinResponse",
        "syncr_api.offplan.schemas.OffPlanPeriodResponse",
        "syncr_api.solving.schemas.OperationResponse",
        "syncr_api.solving.schemas.OperationTarget",
        "syncr_api.plans.proposal_schemas.ProposalDiffResponse",
        "syncr_api.plans.verdict_schemas.VerdictResponse",
        "syncr_api.plans.verdict_schemas.ShortfallResponse",
    } <= reached


def test_the_optionality_check_reports_a_field_that_gained_a_default() -> None:
    """The control: a rule whose test cannot fail is indistinguishable from one nobody enforces."""

    class _Drifted(WireModel):
        required: int
        drifted: int | None = None

    assert optional_fields(_Drifted) == frozenset({"drifted"})


def test_every_clause_shape_declares_the_discriminator_the_exemption_names() -> None:
    """So the exemption above cannot quietly cover a field that is not a discriminator."""
    for member in _wire_clauses():
        assert optional_fields(member) <= {DISCRIMINATOR}, member
        assert DISCRIMINATOR in member.model_fields, member
