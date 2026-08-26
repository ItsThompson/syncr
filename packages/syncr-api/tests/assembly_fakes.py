"""Fakes and builders for the week assembler's tier-2 suite.

Sixteen collaborators is the component's nature, so a test that spelled all sixteen would be a
test about wiring. :func:`an_assembler` composes them and takes an override per seam, so each test
states only the stored state its own resolution reads.

Every fake is the REAL repository's interface over a list of records and no database. The domain is
real throughout: the zone resolution, the interval algebra, the cursor, the debt figure, the budget
arithmetic, and every value type are the shipped ones, because a stubbed derivation would let this
suite pass while a figure was wrong.

Two seams are protocols rather than repositories, and both are supplied here with real content:
the habit outcome log and the week's placements. Production wires readers that answer with
nothing, so without these the netting rules and the two derivations could only ever be asserted
against an empty week.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from syncr_api.anchors import rules
from syncr_api.anchors.records import AnchorRecord, AnchorTypeRecord, AnchorTypeSpecification
from syncr_api.anchors.repository import AnchorRepository
from syncr_api.anchors.type_repository import AnchorTypeRepository
from syncr_api.areas.records import AreaRecord
from syncr_api.areas.repository import AreaRepository
from syncr_api.habits.records import HabitRecord
from syncr_api.habits.repository import HabitRepository
from syncr_api.learned.config import HAND_TUNED, P0_WEIGHTS
from syncr_api.learned.records import WeightSetRecord
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.offplan.records import OffPlanPeriodRecord
from syncr_api.offplan.repository import OffPlanPeriodRepository
from syncr_api.plans.adjustments import WeekAdjustmentRepository
from syncr_api.plans.assembler import AssemblyCaller, WeekAssembler
from syncr_api.plans.placements import WeekPlacements
from syncr_api.plans.records import PlanRevisionRecord, WeekAdjustmentRecord
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.preferences.records import PreferenceRecord, windows_as_json
from syncr_api.preferences.repository import PreferenceRepository
from syncr_api.routines.records import RoutineRecord
from syncr_api.routines.repository import RoutineRepository
from syncr_api.tasks.records import TaskRecord
from syncr_api.tasks.repository import TaskRepository
from syncr_api.templates.records import TemplateEntryRecord, TemplateRecord
from syncr_api.templates.repository import TemplateRepository, WeekPatternRepository
from syncr_api.user_settings.config import ReviewCadence
from syncr_api.user_settings.records import SettingsRecord, TravelOverrideRecord
from syncr_api.user_settings.repository import SettingsRepository, TravelOverrideRepository
from syncr_domain.fixtures.dst_weeks import LONDON
from syncr_domain.habits import BindingSource, CadenceKind, Duration, MissPolicy
from syncr_domain.identity import BindingRef
from syncr_domain.intervals import Interval
from syncr_domain.plan import Block, PlanDocument
from syncr_domain.preferences import (
    LocalTimeWindow,
    PreferenceOwner,
    PreferenceOwnerKind,
    PreferenceStrength,
)
from syncr_domain.reasons import Bound, DerivationSource, ReasonRecord
from syncr_domain.tasks import Priority, TaskStatus
from syncr_domain.templates import BindingTarget, EntrySpan, TemplateEntryKind, WeekPattern
from syncr_domain.weeks import IsoWeek, Weekday, active_zone_by_date
from syncr_domain.zones import ZoneProfile
from syncr_solver.inputs import Pin

if TYPE_CHECKING:
    from collections.abc import Sequence
    from decimal import Decimal

    from syncr_api.anchors.records import AnchorTypeId
    from syncr_api.core.columns import JsonObject
    from syncr_api.habits.outcome_log import HabitOutcomeReader
    from syncr_api.plans.config import AdjustmentKind
    from syncr_api.plans.placements import WeekPlacementReader
    from syncr_domain.identifiers import AreaId, HabitId, TaskId
    from syncr_domain.outcomes import HabitOutcome, RecordedOutcome
    from syncr_domain.zones import Date

TENANT = UUID("11111111-1111-4111-8111-111111111111")
# The calendar every imported commitment in this suite came from. One source, because which feed
# published a commitment decides nothing an assembly reads.
SOURCE = UUID("22222222-2222-4222-8222-222222222222")

# A week with no daylight-saving transition in it, so a figure that differs between two of its
# days differs for the reason the test is about.
WEEK = IsoWeek(2026, 7)
MONDAY = WEEK.monday()
# 2026-W07 in London is on GMT throughout, so local midnight is UTC midnight.
MONDAY_MIDNIGHT = datetime(2026, 2, 9, tzinfo=UTC)
# Wednesday mid-morning: half the week is past and half is future, which is what makes the
# immovable half of every netting rule reachable.
NOW = datetime(2026, 2, 11, 9, 0, tzinfo=UTC)

MINUTES_PER_HOUR = 60

A_REASON = ReasonRecord((Bound(DerivationSource.ROUTINE, "Sleep · 23:00 + 8h"),))


def at(hour: float, *, day: int = 0) -> datetime:
    """An instant inside ``WEEK``, ``hour`` hours into the ``day``-th day."""
    return MONDAY_MIDNIGHT + timedelta(days=day, hours=hour)


def between(start_hour: float, end_hour: float, *, day: int = 0) -> Interval:
    return Interval(at(start_hour, day=day), at(end_hour, day=day))


def an_area(
    *,
    area_id: AreaId | None = None,
    name: str = "Fitness",
    floor_hours: Decimal | None = None,
    budget_percent: Decimal | None = None,
    parent_id: AreaId | None = None,
) -> AreaRecord:
    return AreaRecord(
        id=area_id or uuid4(),
        tenant_id=TENANT,
        parent_id=parent_id,
        name=name,
        pigment_index=1,
        budget_percent=budget_percent,
        floor_hours=floor_hours,
        created_at=MONDAY_MIDNIGHT,
    )


def a_task(
    *,
    task_id: TaskId | None = None,
    area_id: AreaId,
    title: str = "F&F Past Papers",
    estimate_minutes: int = 240,
    recorded_minutes: int = 0,
    deadline: datetime | None = None,
    status: TaskStatus = TaskStatus.OPEN,
    min_chunk_minutes: int = 30,
    splittable: bool = True,
    priority: Priority = Priority.NORMAL,
) -> TaskRecord:
    return TaskRecord(
        id=task_id or uuid4(),
        tenant_id=TENANT,
        area_id=area_id,
        project_id=None,
        title=title,
        estimate_minutes=estimate_minutes,
        deadline=deadline,
        priority=priority,
        min_chunk_minutes=min_chunk_minutes,
        splittable=splittable,
        status=status,
        recorded_minutes=recorded_minutes,
        completed_at=None,
        created_at=MONDAY_MIDNIGHT,
    )


def a_habit(
    *,
    habit_id: HabitId | None = None,
    area_id: AreaId,
    title: str = "Gym",
    cadence_kind: CadenceKind = CadenceKind.TIMES_PER_WEEK,
    times_per_week: int | None = 4,
    approx_days: int | None = None,
    duration: Duration | None = None,
    miss_policy: MissPolicy = MissPolicy.FORGIVE,
    binding_source: BindingSource = BindingSource.FIXED,
    variants: tuple[str, ...] = (),
    debt_cap_periods: int = 2,
    charged_misses: int = 0,
) -> HabitRecord:
    span = duration or Duration.fixed(60)
    return HabitRecord(
        id=habit_id or uuid4(),
        tenant_id=TENANT,
        area_id=area_id,
        title=title,
        cadence_kind=cadence_kind,
        cadence_times_per_week=times_per_week,
        cadence_approx_days=approx_days,
        duration_min_minutes=span.min_minutes,
        duration_max_minutes=span.max_minutes,
        miss_policy=miss_policy,
        binding_source=binding_source,
        variants=variants,
        debt_cap_periods=debt_cap_periods,
        charged_misses=charged_misses,
        created_at=MONDAY_MIDNIGHT,
    )


def a_routine(
    *,
    routine_id: UUID | None = None,
    title: str = "Sleep",
    target_time: time = time(23, 0),
    duration_minutes: int = 8 * MINUTES_PER_HOUR,
    min_duration_minutes: int | None = None,
    flex_band_minutes: int = 30,
) -> RoutineRecord:
    return RoutineRecord(
        id=routine_id or uuid4(),
        tenant_id=TENANT,
        title=title,
        target_time=target_time,
        duration_minutes=duration_minutes,
        min_duration_minutes=(
            duration_minutes if min_duration_minutes is None else min_duration_minutes
        ),
        flex_band_minutes=flex_band_minutes,
        created_at=MONDAY_MIDNIGHT,
    )


def a_slot_entry(
    *,
    entry_id: UUID | None = None,
    template_id: UUID,
    area_id: AreaId,
    target_time: time = time(18, 0),
    duration_minutes: int = 60,
    flex_band_minutes: int = 15,
) -> TemplateEntryRecord:
    return TemplateEntryRecord(
        id=entry_id or uuid4(),
        tenant_id=TENANT,
        template_id=template_id,
        kind=TemplateEntryKind.SLOT,
        span=EntrySpan(
            target_time=target_time,
            duration_minutes=duration_minutes,
            flex_band_minutes=flex_band_minutes,
        ),
        area_id=area_id,
        binding_target=None,
        binding_ref=None,
    )


def a_concrete_entry(
    *,
    entry_id: UUID | None = None,
    template_id: UUID,
    target: BindingTarget = BindingTarget.HABIT,
    entity_id: UUID | None = None,
    area_id: AreaId | None = None,
    target_time: time = time(6, 45),
    duration_minutes: int = 15,
) -> TemplateEntryRecord:
    return TemplateEntryRecord(
        id=entry_id or uuid4(),
        tenant_id=TENANT,
        template_id=template_id,
        kind=TemplateEntryKind.CONCRETE,
        span=EntrySpan(
            target_time=target_time, duration_minutes=duration_minutes, flex_band_minutes=0
        ),
        area_id=area_id,
        binding_target=target,
        binding_ref=entity_id or uuid4(),
    )


def a_template(
    *,
    template_id: UUID | None = None,
    day_type_id: UUID,
    name: str = "Weekday",
    entries: Sequence[TemplateEntryRecord] = (),
) -> TemplateRecord:
    return TemplateRecord(
        id=template_id or uuid4(),
        tenant_id=TENANT,
        day_type_id=day_type_id,
        name=name,
        created_at=MONDAY_MIDNIGHT,
        entries=tuple(entries),
    )


def every_day(day_type_id: UUID) -> WeekPattern:
    """One day type on all seven weekdays, which is the smallest complete pattern."""
    return WeekPattern(dict.fromkeys(Weekday, day_type_id))


def a_preference(
    *,
    owner: PreferenceOwner,
    windows: Sequence[LocalTimeWindow] = (),
    strength: PreferenceStrength = PreferenceStrength.SOFT,
    preferred_duration_minutes: int | None = None,
    max_per_day_minutes: int | None = None,
) -> PreferenceRecord:
    return PreferenceRecord(
        id=uuid4(),
        tenant_id=TENANT,
        owner=owner,
        windows=tuple(windows_as_json(list(windows))),
        strength=strength,
        preferred_duration_minutes=preferred_duration_minutes,
        max_per_day_minutes=max_per_day_minutes,
        created_at=MONDAY_MIDNIGHT,
    )


def an_area_owner(area_id: AreaId) -> PreferenceOwner:
    return PreferenceOwner(kind=PreferenceOwnerKind.AREA, id=area_id)


def a_habit_owner(habit_id: HabitId) -> PreferenceOwner:
    return PreferenceOwner(kind=PreferenceOwnerKind.HABIT, id=habit_id)


def a_window(start: time, end: time) -> LocalTimeWindow:
    return LocalTimeWindow(start=start, end=end)


def an_off_plan_period(
    *, interval: Interval, keep_frame: bool = False, label: str | None = None
) -> OffPlanPeriodRecord:
    return OffPlanPeriodRecord(
        id=uuid4(),
        tenant_id=TENANT,
        interval=interval,
        keep_frame=keep_frame,
        label=label,
        created_at=MONDAY_MIDNIGHT,
    )


def a_weight_set(
    *, duration_multiplier: dict[str, Any] | None = None, version: int = 1
) -> WeightSetRecord:
    return WeightSetRecord(
        tenant_id=TENANT,
        version=version,
        active=True,
        origin=HAND_TUNED,
        deadline_risk=P0_WEIGHTS["deadline_risk"],
        budget_deviation=P0_WEIGHTS["budget_deviation"],
        time_of_day_misfit=P0_WEIGHTS["time_of_day_misfit"],
        fragmentation=P0_WEIGHTS["fragmentation"],
        churn=P0_WEIGHTS["churn"],
        context_switch=P0_WEIGHTS["context_switch"],
        staleness=P0_WEIGHTS["staleness"],
        duration_multiplier=duration_multiplier or {},
        time_of_day_fitness={},
        skip_probability={},
        context_switch_cost=P0_WEIGHTS["context_switch_cost"],
        churn_tolerance=P0_WEIGHTS["churn_tolerance"],
        fitted_at=None,
        maturity=[],
        created_at=MONDAY_MIDNIGHT,
    )


def an_adjustment(
    *,
    kind: AdjustmentKind,
    target_id: UUID,
    reductions: dict[str, Any] | None = None,
    delta_minutes: int | None = None,
) -> WeekAdjustmentRecord:
    return WeekAdjustmentRecord(
        id=uuid4(),
        tenant_id=TENANT,
        iso_week=WEEK,
        kind=kind,
        target_id=target_id,
        reductions=reductions or {},
        delta_minutes=delta_minutes,
        created_at=MONDAY_MIDNIGHT,
        created_by_operation_id=uuid4(),
    )


def an_approved_revision(*, approved_at: datetime, document: JsonObject) -> PlanRevisionRecord:
    """One revision the user assented to, carrying the plan it stored.

    ``document`` has no default, so every caller states the plan its week was approved with. The
    baseline reads it, and a default nothing could rebuild would put a caller in the unreadable
    state without asking for it.
    """
    return PlanRevisionRecord(
        id=uuid4(),
        tenant_id=TENANT,
        iso_week=WEEK,
        status="approved",
        reason="user_approved",
        document=document,
        objective_breakdown={},
        weight_set_version=1,
        input_version=3,
        supersedes_id=None,
        created_at=MONDAY_MIDNIGHT,
        approved_at=approved_at,
    )


def a_task_block(
    *,
    task_id: TaskId,
    area_id: AreaId,
    interval: Interval,
    split_index: int | None = None,
    split_count: int | None = None,
) -> Block:
    """One placed block of a task, as a stored plan document holds it.

    Several placements of ONE task in one week are its CHUNKS: a document refuses two blocks
    sharing a binding, and a task's binding is keyed by its chunk, so an unsplit task has exactly
    one block. That is why every test placing a task twice numbers the chunks.
    """
    return Block(
        iso_week=WEEK,
        interval=interval,
        binding=BindingRef.for_task(task_id, split_index=split_index),
        title="F&F Past Papers",
        reason=A_REASON,
        area_id=area_id,
        split_count=None if split_index is None else (split_count or 2),
    )


def a_habit_block(
    *, habit_id: HabitId, area_id: AreaId, interval: Interval, index: int = 0
) -> Block:
    return Block(
        iso_week=WEEK,
        interval=interval,
        binding=BindingRef.for_habit(habit_id, index=index),
        title="Gym",
        reason=A_REASON,
        area_id=area_id,
    )


def a_plan(*, blocks: Sequence[Block] = (), profile: ZoneProfile | None = None) -> PlanDocument:
    """A live plan holding ``blocks``. Its figures are not what any of these tests read."""
    return PlanDocument(
        iso_week=WEEK,
        zone_by_date=active_zone_by_date(WEEK, profile or ZoneProfile(LONDON)),
        discretionary_minutes=0,
        unallocated_minutes=0,
        oversubscription_minutes=0,
        blocks=tuple(blocks),
    )


def a_pin(*, binding: BindingRef, interval: Interval, pinned_on: Date | None = None) -> Pin:
    return Pin(binding=binding, interval=interval, pinned_on=pinned_on or MONDAY)


class FakeSettings(SettingsRepository):
    def __init__(self, home_zone: str = LONDON) -> None:
        self._home_zone = home_zone

    async def read(self) -> SettingsRecord:
        return SettingsRecord(
            tenant_id=TENANT,
            visible_hours=18,
            day_start=time(6, 0),
            day_end=time(0, 0),
            review_cadence=ReviewCadence.ON_DEMAND,
            home_zone=self._home_zone,
        )


class FakeOverrides(TravelOverrideRepository):
    def __init__(self, stored: Sequence[TravelOverrideRecord] = ()) -> None:
        self._stored = tuple(stored)

    async def list_all(self) -> tuple[TravelOverrideRecord, ...]:
        return self._stored


def a_travel_override(*, start_date: Date, end_date: Date, zone: str) -> TravelOverrideRecord:
    return TravelOverrideRecord(
        id=uuid4(), tenant_id=TENANT, start_date=start_date, end_date=end_date, zone=zone
    )


class FakeRoutines(RoutineRepository):
    def __init__(self, stored: Sequence[RoutineRecord] = ()) -> None:
        self._stored = tuple(stored)

    async def list_all(self) -> tuple[RoutineRecord, ...]:
        return tuple(sorted(self._stored, key=lambda row: (row.target_time, row.id)))


class FakeWeekPattern(WeekPatternRepository):
    def __init__(self, pattern: WeekPattern | None = None) -> None:
        self._pattern = pattern

    async def read(self) -> WeekPattern | None:
        return self._pattern


class FakeTemplates(TemplateRepository):
    def __init__(self, stored: Sequence[TemplateRecord] = ()) -> None:
        self._stored = tuple(stored)

    async def list_all(self) -> tuple[TemplateRecord, ...]:
        return self._stored


class FakeHabits(HabitRepository):
    def __init__(self, stored: Sequence[HabitRecord] = ()) -> None:
        self._stored = tuple(stored)

    async def list_all(self, *, area_id: AreaId | None = None) -> tuple[HabitRecord, ...]:
        return tuple(row for row in self._stored if area_id is None or row.area_id == area_id)


class FakeOutcomes:
    """The outcome log seam, with content. Records which habits were asked for."""

    def __init__(self, stored: Sequence[HabitOutcome] = ()) -> None:
        self._stored = tuple(stored)
        self.asked_for: list[HabitId] = []

    async def read(self, habit_ids: Sequence[HabitId]) -> tuple[HabitOutcome, ...]:
        self.asked_for.extend(habit_ids)
        return tuple(row for row in self._stored if row.habit_id in set(habit_ids))

    async def latest(
        self, habit_ids: Sequence[HabitId], *, since: datetime
    ) -> dict[HabitId, datetime | None]:
        latest_seen: dict[HabitId, datetime | None] = dict.fromkeys(habit_ids)
        for row in self._stored:
            if row.habit_id in latest_seen and row.occurred_at >= since:
                seen = latest_seen[row.habit_id]
                if seen is None or row.occurred_at > seen:
                    latest_seen[row.habit_id] = row.occurred_at
        return latest_seen

    async def settled_within(
        self, habit_ids: Sequence[HabitId], *, span: Interval
    ) -> tuple[HabitOutcome, ...]:
        asked = set(habit_ids)
        return tuple(
            row
            for row in self._stored
            if row.habit_id in asked
            and row.confirmed_at is not None
            and span.start <= row.confirmed_at < span.end
        )


class FakeTasks(TaskRepository):
    def __init__(self, stored: Sequence[TaskRecord] = ()) -> None:
        self._stored = tuple(stored)

    async def list_all(
        self, *, area_id: AreaId | None = None, status: TaskStatus | None = None
    ) -> tuple[TaskRecord, ...]:
        return tuple(
            row
            for row in self._stored
            if (area_id is None or row.area_id == area_id)
            and (status is None or row.status == status)
        )


class FakeAreas(AreaRepository):
    def __init__(self, stored: Sequence[AreaRecord] = ()) -> None:
        self._stored = tuple(stored)

    async def list_all(self) -> tuple[AreaRecord, ...]:
        return self._stored


class FakePreferences(PreferenceRepository):
    def __init__(self, stored: Sequence[PreferenceRecord] = ()) -> None:
        self._stored = tuple(stored)

    async def list_all(self) -> tuple[PreferenceRecord, ...]:
        return self._stored


class FakeOffPlan(OffPlanPeriodRepository):
    def __init__(self, stored: Sequence[OffPlanPeriodRecord] = ()) -> None:
        self._stored = tuple(stored)

    async def for_span(self, span: Interval) -> tuple[OffPlanPeriodRecord, ...]:
        return tuple(row for row in self._stored if row.interval.overlaps(span))


class FakePlacements:
    """The placement seam, with content: a live plan, its pins, and the outcomes recorded on it."""

    def __init__(
        self,
        *,
        live_plan: PlanDocument | None = None,
        pins: Sequence[Pin] = (),
        outcomes: Sequence[RecordedOutcome] = (),
    ) -> None:
        self._placements = WeekPlacements(
            live_plan=live_plan, pins=tuple(pins), outcomes=tuple(outcomes)
        )

    async def read(self, iso_week: IsoWeek, span: Interval) -> WeekPlacements:
        return self._placements


class FakeAdjustments(WeekAdjustmentRepository):
    def __init__(self, stored: Sequence[WeekAdjustmentRecord] = ()) -> None:
        self._stored = tuple(stored)

    async def for_week(self, iso_week: IsoWeek) -> list[WeekAdjustmentRecord]:
        return [row for row in self._stored if row.iso_week == iso_week]


class FakeAnchors(AnchorRepository):
    """The anchors a tenant holds, answering the assembly's unpaged span read.

    Records which spans were asked for, because what an assembly reads beyond its own week is a
    claim about the expansion rather than about the rows that came back.
    """

    def __init__(self, stored: Sequence[AnchorRecord] = ()) -> None:
        self._stored = tuple(stored)
        self.asked_for: list[Interval] = []

    async def overlapping(self, span: Interval) -> tuple[AnchorRecord, ...]:
        self.asked_for.append(span)
        found = [row for row in self._stored if row.interval.overlaps(span)]
        return tuple(sorted(found, key=lambda row: (row.interval, row.id)))


class FakeAnchorTypes(AnchorTypeRepository):
    def __init__(self, stored: Sequence[AnchorTypeRecord] = ()) -> None:
        self._stored = tuple(stored)

    async def list_all(self) -> tuple[AnchorTypeRecord, ...]:
        return self._stored


def an_anchor_type(
    specification: AnchorTypeSpecification, *, rule_order: int = 0
) -> AnchorTypeRecord:
    """``specification`` as a stored row, refused here if the boundary rules would refuse it.

    Validated so every geometry these tests read is one a tenant could really hold: a declaration
    the rules reject describes a shadow the product cannot cast, and asserting arithmetic over one
    asserts it against itself. The Areas it names count as declared, because a specification
    naming an Area is what a suite with a real tenant would have created.
    """
    rules.validate(
        specification,
        declared_areas=set(specification.referenced_area_ids),
        declared_sources=(
            () if specification.match_source_id is None else (specification.match_source_id,)
        ),
    )
    return AnchorTypeRecord(
        id=uuid4(), tenant_id=TENANT, rule_order=rule_order, specification=specification
    )


def an_anchor(
    *,
    interval: Interval,
    anchor_type: AnchorTypeRecord | None = None,
    title: str = "Kontron Placement Interview",
    anchor_type_id: AnchorTypeId | None = None,
) -> AnchorRecord:
    """One imported commitment, carrying ``anchor_type`` or the identifier given instead.

    ``anchor_type_id`` is separate so a test can store the state a race produces: an anchor
    carrying a type the types read did not return.
    """
    return AnchorRecord(
        id=uuid4(),
        tenant_id=TENANT,
        source_id=SOURCE,
        external_uid=f"{title}-{interval.start.isoformat()}@example.ac.uk",
        series_uid=None,
        title=title,
        interval=interval,
        location=None,
        anchor_type_id=anchor_type_id or (None if anchor_type is None else anchor_type.id),
        type_overridden=False,
        possibly_stale=False,
    )


class FakeWeights(WeightSetRepository):
    def __init__(self, active: WeightSetRecord | None = None) -> None:
        self._active = active

    async def active(self) -> WeightSetRecord | None:
        return self._active


class FakeVersions(WeekInputVersionRepository):
    def __init__(self, current: int | None = None) -> None:
        self._current = current

    async def current(self, iso_week: IsoWeek) -> int | None:
        return self._current


class FakeRevisions(PlanRepository):
    """The two questions the plan of record is asked, over values rather than a table.

    One fake for both, because they are two questions about one table and a second fake answering
    the other is how a third arrives the first time a test needs them together.

    ``weeks_with_a_plan`` answers :meth:`holds_a_plan`, which is a boolean and needs no record: the
    readers that gate on the absence never open the document, which is why that method exists.
    """

    def __init__(
        self,
        latest_approved: PlanRevisionRecord | None = None,
        *,
        weeks_with_a_plan: Sequence[IsoWeek] = (),
    ) -> None:
        self._latest_approved = latest_approved
        self._weeks_with_a_plan = tuple(weeks_with_a_plan)

    async def latest_approved(self, iso_week: IsoWeek) -> PlanRevisionRecord | None:
        return self._latest_approved

    async def holds_a_plan(self, iso_week: IsoWeek) -> bool:
        return iso_week in self._weeks_with_a_plan


def an_assembler(
    *,
    settings: SettingsRepository | None = None,
    overrides: TravelOverrideRepository | None = None,
    routines: RoutineRepository | None = None,
    week_pattern: WeekPatternRepository | None = None,
    templates: TemplateRepository | None = None,
    habits: HabitRepository | None = None,
    outcomes: HabitOutcomeReader | None = None,
    tasks: TaskRepository | None = None,
    areas: AreaRepository | None = None,
    preferences: PreferenceRepository | None = None,
    off_plan: OffPlanPeriodRepository | None = None,
    placements: WeekPlacementReader | None = None,
    adjustments: WeekAdjustmentRepository | None = None,
    anchors: AnchorRepository | None = None,
    anchor_types: AnchorTypeRepository | None = None,
    weights: WeightSetRepository | None = None,
    versions: WeekInputVersionRepository | None = None,
    revisions: PlanRepository | None = None,
    caller: AssemblyCaller = AssemblyCaller.REQUEST,
) -> WeekAssembler:
    """An assembler over fakes, with every seam empty unless a test supplies it."""
    return WeekAssembler(
        settings=settings or FakeSettings(),
        overrides=overrides or FakeOverrides(),
        routines=routines or FakeRoutines(),
        week_pattern=week_pattern or FakeWeekPattern(),
        templates=templates or FakeTemplates(),
        habits=habits or FakeHabits(),
        outcomes=outcomes or FakeOutcomes(),
        tasks=tasks or FakeTasks(),
        areas=areas or FakeAreas(),
        preferences=preferences or FakePreferences(),
        off_plan=off_plan or FakeOffPlan(),
        placements=placements or FakePlacements(),
        adjustments=adjustments or FakeAdjustments(),
        anchors=anchors or FakeAnchors(),
        anchor_types=anchor_types or FakeAnchorTypes(),
        weights=weights or FakeWeights(a_weight_set()),
        versions=versions or FakeVersions(3),
        revisions=revisions or FakeRevisions(),
        caller=caller,
    )


def an_outcome_date(*, day: int) -> date:
    """A local date inside ``WEEK``, for a fixture that keys by one."""
    return MONDAY + timedelta(days=day)
