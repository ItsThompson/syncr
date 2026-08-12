"""The week assembler: stored state in, one resolved ``SolveInputs`` out.

The widest integration point in the product. One method, three arguments, one return type, and
behind that interface every resolution the solver and the probe are deliberately spared. Their
purity is only possible because this component absorbs the impurity: the solver performs no
lookup, derives no domain projection, and reads no clock, so it is testable against literals.

## The pipeline, and the count that is load-bearing

**Eighteen resolutions over nineteen repository reads.** The figure is stated once, here, and the
bullets below are counted to match it, because a latency budget and an alert are calibrated to
it: an assembly is budgeted at p95 under 100 ms against reads on a warm cache, and the assembly
histogram's alert is read against that budget. **The budget and the alert were both set against a
figure of eleven, which was never counted; recalibrating them is its own piece of work, and
restating the figure here does not do it.** One of the eighteen performs four statements behind a
single call, named below.

```
assemble(iso_week, now, extra_adjustment=None)
  ├── resolve the week span, DST-correct, across a possible travel boundary
  ├── resolve each day's active zone
  ├── read the input version, from which the seed derives
  ├── name the churn baseline: the last approved revision and the plan it stored, or
  │     never-approved
  ├── read what the week already holds: the live plan, its pins and its outcomes, keeping
  │     only the pins whose placement the week has not yet reached
  ├── load off-plan periods, over this week and the one before it, and clip them per week
  ├── materialize routines: local target times to instants, at EFFECTIVE durations
  │     clamped to min_duration_minutes, one occurrence per day, each keyed by date
  ├── carry the PRECEDING week's boundary-crossing occurrences as the spans they occupy
  │     here, resolved as that week resolves them, its own concessions folded in
  ├── materialize template entries from the week pattern and the day types, keyed by date,
  │     each concrete one named and charged by the routine or habit row it binds
  ├── expand habit cadence into occurrences, keyed by index in expansion order
  │     ├── derive each rotation cursor from the outcome log
  │     └── apply outstanding debt, capped
  ├── read the active weight set's duration multipliers, gated by maturity
  ├── read the anchor types, and the anchors of the span they widen it to, pairing each
  │     anchor with the type it carries
  ├── generate what every loaded anchor casts, clip it to the week, drop what is left with
  │     nothing in it, and suppress the BLOCKS a declared off-plan span covers
  ├── collect eligible tasks, netting recorded minutes and IMMOVABLE placements only
  ├── compute the demand per deadline, netting EVERY placement falling before it
  ├── compute per-Area floor minutes, floor reservations, gross targets, and daily caps
  ├── FOLD approved concessions, plus a candidate when one is being evaluated,
  │     as a POST-PASS over the six resolved quantities above that they modify
  └── resolve preferences down the Area to Habit or Task override chain, windows to instants,
        over the FOLDED eligibility, so a dropped task's window goes with it
```

**Folding is a post-pass, and the one resolution after it reads its output.** Every quantity a
concession changes is resolved before the fold runs, so a reader asking what a concession touches
reads one function rather than tracing a pipeline. Preferences follow rather than precede it,
because a window resolved for a task this week will not schedule is a window with no consumer.

A candidate concession being evaluated is an argument rather than a table read, which is what keeps
a tradeoff request from persisting anything.

**One collaborator is read twice, and it is the concession table.** The week being assembled and
the week before it each have their own approved concessions, and the inherited occurrence has to
be resolved as its own week resolves it or the two weeks disagree about how long one night was.

## One resolution costs four statements, and the read figure counts the call

*The live plan, its pins and its outcomes* are read for real. One collaborator call, and four
statements behind it: that gap is stated on the seam itself, because the p95 budgets in section 19
are calibrated against the collaborator figure above, and this is the collaborator the two figures
differ over most.

## What this method never does

It reads no clock: ``now`` is stamped from its own argument, so an assembly is reproducible and a
caller can assemble against a past instant when reproducing a failure. It writes nothing at all,
not a row and not a version bump, so a read cannot change what the next solve sees. And it mints
no value a caller could supply wrongly: the seed is derived from the week and the input version on
read.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from prometheus_client import Histogram

from syncr_api.anchors.reach import casting_span
from syncr_api.plans.cadence import habit_occurrences
from syncr_api.plans.calendar_occupancy import calendar_occupancy, typed_anchors
from syncr_api.plans.candidates import reductions_of
from syncr_api.plans.demand import deadline_demands, eligible_tasks, task_demands
from syncr_api.plans.errors import StoredDocumentCorrupt
from syncr_api.plans.folding import Concessions, fold
from syncr_api.plans.materialization import (
    OffPlanSuppression,
    frame_entries,
    materialized_entries,
    periods_of,
)
from syncr_api.plans.multipliers import DurationMultipliers
from syncr_api.plans.netting import PlacedTime, placements
from syncr_api.plans.overhang import frame_overhang
from syncr_api.plans.placements import constraining
from syncr_api.plans.reservations import area_budgets
from syncr_api.plans.resolved_preferences import area_caps, resolved_preferences
from syncr_api.plans.stored_documents import plan_document
from syncr_api.user_settings.zone_reading import as_domain, zone_profile
from syncr_common.logging import get_logger
from syncr_common.metrics import REGISTRY, measured
from syncr_domain.discretionary import discretionary_time
from syncr_domain.intervals import Interval, IntervalSet
from syncr_domain.plan import AdjustmentKind
from syncr_domain.weeks import active_zone_by_date, week_span
from syncr_solver.inputs import ChurnBaseline, SolveInputs, WeekAdjustment, frame_occupancy

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from syncr_api.anchors.repository import AnchorRepository
    from syncr_api.anchors.type_repository import AnchorTypeRepository
    from syncr_api.areas.repository import AreaRepository
    from syncr_api.habits.outcome_log import HabitOutcomeReader
    from syncr_api.habits.repository import HabitRepository
    from syncr_api.learned.repository import WeightSetRepository
    from syncr_api.offplan.repository import OffPlanPeriodRepository
    from syncr_api.plans.adjustments import WeekAdjustmentRepository
    from syncr_api.plans.calendar_occupancy import CalendarOccupancy
    from syncr_api.plans.placements import WeekPlacementReader
    from syncr_api.plans.records import PlanRevisionRecord, WeekAdjustmentRecord
    from syncr_api.plans.repository import PlanRepository
    from syncr_api.plans.versions import WeekInputVersionRepository
    from syncr_api.preferences.repository import PreferenceRepository
    from syncr_api.routines.repository import RoutineRepository
    from syncr_api.tasks.repository import TaskRepository
    from syncr_api.templates.repository import TemplateRepository, WeekPatternRepository
    from syncr_api.user_settings.repository import SettingsRepository, TravelOverrideRepository
    from syncr_domain.off_plan import OffPlanPeriod
    from syncr_domain.plan import PlanDocument
    from syncr_domain.weeks import IsoWeek
    from syncr_domain.zones import Date
    from syncr_solver.inputs import FrameEntry

_log = get_logger("syncr.plans")

# How many resolutions the pipeline above performs, stated once so the docstring, the alert, and
# the latency budget read one figure. `test_week_assembler.py` counts the bullets against it.
RESOLUTION_COUNT = 18

# How many repository reads one assembly performs. The dominant cost of every request that
# returns a live verdict, which is what the assembly histogram exists to make visible. Nineteen
# reads over eighteen collaborators: the concession table is read once per week, for this week and
# for the one whose boundary-crossing occurrences this week inherits.
REPOSITORY_READ_COUNT = 19

# The version an assembly of a week nothing has referenced reports. A missing row is a MISMATCH
# to the conditional write rather than a match, so a first solve's write is superseded and its
# follow-up reads the row that write created. Reporting the first version instead would let two
# concurrent first solves both believe they held current inputs.
UNVERSIONED_WEEK = 0

ASSEMBLY_DURATION = Histogram(
    "syncr_assembly_duration_seconds",
    "Time to assemble one week's solve inputs, by the caller that asked for it.",
    labelnames=("caller",),
    registry=REGISTRY,
)


class AssemblyCaller(StrEnum):
    """Who asked for an assembly. The one label on the assembly histogram.

    Labeled by caller because the alert is scoped to the interactive one: every mutation that
    returns a live verdict assembles first, so a regression there is a regression in the product's
    responsiveness, and the maintainer's hundreds of background assemblies a day must not mask it
    or trigger it.
    """

    REQUEST = "request"
    WORKER = "worker"
    MAINTAINER = "maintainer"


class WeekAssembler:
    """Turn stored state into one resolved, self-contained ``SolveInputs``.

    Eighteen collaborators plus the caller, and that is the component's nature rather than an
    accident: this is where every ounce of complexity the solver sheds actually lands. A caller
    cannot get it partially right, because there is nothing to get partially right.
    """

    def __init__(
        self,
        *,
        settings: SettingsRepository,
        overrides: TravelOverrideRepository,
        routines: RoutineRepository,
        week_pattern: WeekPatternRepository,
        templates: TemplateRepository,
        habits: HabitRepository,
        outcomes: HabitOutcomeReader,
        tasks: TaskRepository,
        areas: AreaRepository,
        preferences: PreferenceRepository,
        off_plan: OffPlanPeriodRepository,
        placements: WeekPlacementReader,
        adjustments: WeekAdjustmentRepository,
        anchors: AnchorRepository,
        anchor_types: AnchorTypeRepository,
        weights: WeightSetRepository,
        versions: WeekInputVersionRepository,
        revisions: PlanRepository,
        caller: AssemblyCaller,
    ) -> None:
        self._settings = settings
        self._overrides = overrides
        self._routines = routines
        self._week_pattern = week_pattern
        self._templates = templates
        self._habits = habits
        self._outcomes = outcomes
        self._tasks = tasks
        self._areas = areas
        self._preferences = preferences
        self._off_plan = off_plan
        self._placements = placements
        self._adjustments = adjustments
        self._anchors = anchors
        self._anchor_types = anchor_types
        self._weights = weights
        self._versions = versions
        self._revisions = revisions
        self._caller = caller

    # `measured` carries the per-method error counter every component in this application has;
    # the histogram beside it carries the caller label, which one label pair cannot express.
    @measured("week_assembler")
    async def assemble(
        self,
        iso_week: IsoWeek,
        now: datetime,
        extra_adjustment: WeekAdjustment | None = None,
    ) -> SolveInputs:
        """Everything a solve of ``iso_week`` reads, resolved against ``now``.

        ``now`` is stamped onto the result rather than read from a clock, so two assemblies of
        unchanged data against one instant are equal, and a caller reproducing a failure can
        assemble against the instant it happened at.

        ``extra_adjustment`` is the concession being evaluated. It folds in exactly like a stored
        one and it is written nowhere, which is what makes requesting a tradeoff free of effect.
        """
        with ASSEMBLY_DURATION.labels(caller=self._caller.value).time():
            return await self._assemble(iso_week, now, extra_adjustment)

    async def _assemble(
        self, iso_week: IsoWeek, now: datetime, extra_adjustment: WeekAdjustment | None
    ) -> SolveInputs:
        profile = zone_profile(
            (await self._settings.read()).home_zone, as_domain(await self._overrides.list_all())
        )
        span = week_span(iso_week, profile)
        zone_by_date = active_zone_by_date(iso_week, profile)
        dates = iso_week.dates()
        preceding = iso_week.preceding()

        input_version = await self._versions.current(iso_week) or UNVERSIONED_WEEK
        churn_baseline = _churn_baseline(await self._revisions.latest_approved(iso_week))
        held = await self._placements.read(iso_week, span)
        # A pin the week has reached is a record rather than a constraint, and the seam states why
        # carrying one wedges the week. Applied here because the rule is a function of the instant
        # this assembly is stamped with, which is exactly what makes a placement immovable below.
        pins = constraining(held.pins, now=now)
        placed = PlacedTime(
            placements(held.live_plan, pins, now=now, outcomes=held.outcomes), now=now
        )
        # Both weeks in one read. The inherited occurrence is judged against the periods of the
        # week that owns it, and reading only this week's would suppress it by a period this week
        # holds or fail to suppress it by one the week before does.
        declared_periods = await self._off_plan.for_span(
            Interval(week_span(preceding, profile).start, span.end)
        )
        off_plan = periods_of(declared_periods, span)

        suppression = OffPlanSuppression(off_plan)
        routines = await self._routines.list_all()
        frame = frame_entries(
            routines,
            dates=dates,
            zone_by_date=zone_by_date,
            off_plan=suppression,
        )
        inherited = frame_overhang(
            routines,
            into=span,
            preceding=preceding,
            profile=profile,
            periods=declared_periods,
            adjustments=_adjustments(
                await self._adjustments.for_week(preceding), None, dates=preceding.dates()
            ),
        )
        habits = await self._habits.list_all()
        template_entries = materialized_entries(
            pattern=await self._week_pattern.read(),
            templates=await self._templates.list_all(),
            routines=routines,
            habits=habits,
            dates=dates,
            zone_by_date=zone_by_date,
            off_plan=suppression,
        )

        multipliers = DurationMultipliers.of(await self._weights.active())
        occurrences = habit_occurrences(
            habits,
            outcomes=await self._outcomes.read([habit.id for habit in habits]),
            now=now,
            multipliers=multipliers,
        )

        calendar = await self._calendar_occupancy(span, off_plan=suppression)

        tasks = await self._tasks.list_all()
        stored_preferences = await self._preferences.list_all()
        declared_areas = await self._areas.list_all()
        resolved = Concessions(
            frame=frame,
            eligible_tasks=eligible_tasks(tasks, placed=placed, multipliers=multipliers),
            demands=task_demands(tasks, placed=placed, multipliers=multipliers),
            areas=area_budgets(
                declared_areas,
                discretionary_minutes=_discretionary_minutes(
                    span,
                    frame=frame,
                    inherited=inherited,
                    calendar=calendar,
                    off_plan=off_plan,
                ),
                placed=placed,
                caps=area_caps(stored_preferences),
            ),
        )

        adjustments = _adjustments(
            await self._adjustments.for_week(iso_week), extra_adjustment, dates=dates
        )
        folded = fold(adjustments, resolved)

        inputs = SolveInputs(
            iso_week=iso_week,
            span=span,
            now=now,
            zone_by_date=zone_by_date,
            input_version=input_version,
            frame=folded.frame,
            frame_overhang=inherited,
            anchors=calendar.anchors,
            shadow_blocks=calendar.shadow_blocks,
            forbidden_windows=calendar.forbidden_windows,
            off_plan=tuple(off_plan),
            template_entries=template_entries,
            habit_occurrences=occurrences,
            eligible_tasks=folded.eligible_tasks,
            areas=folded.areas,
            preferences=resolved_preferences(
                stored_preferences,
                areas=declared_areas,
                habits=habits,
                tasks=folded.eligible_tasks,
                zone_by_date=zone_by_date,
            ),
            pins=pins,
            deadline_demands=deadline_demands(folded.demands),
            adjustments=adjustments,
            live_plan=held.live_plan,
            churn_baseline=churn_baseline,
        )
        _log.info(
            "plans.assembly.completed",
            iso_week=str(iso_week),
            caller=self._caller.value,
            input_version=input_version,
            frame_entries=len(inputs.frame),
            frame_overhang=len(inputs.frame_overhang),
            anchors=len(inputs.anchors),
            shadow_blocks=len(inputs.shadow_blocks),
            forbidden_windows=len(inputs.forbidden_windows),
            template_entries=len(inputs.template_entries),
            habit_occurrences=len(inputs.habit_occurrences),
            eligible_tasks=len(inputs.eligible_tasks),
            deadline_demands=len(inputs.deadline_demands),
            adjustments=len(inputs.adjustments),
        )
        return inputs

    async def _calendar_occupancy(
        self, span: Interval, *, off_plan: OffPlanSuppression
    ) -> CalendarOccupancy:
        """The commitments this week holds, and everything their types cast inside it.

        The types are read first, which is the cheaper order rather than a safe one: two statements
        read a snapshot each under Postgres' default isolation, and releasing a type from its
        anchors and deleting it are one transaction, so a delete that commits between the two reads
        is answered by anchors that no longer carry it and nothing degrades. The opposite race, a
        type created between them, is what the pairing's own guard covers.
        """
        types = await self._anchor_types.list_all()
        loaded = await self._anchors.overlapping(
            casting_span(span, tuple(row.specification for row in types))
        )
        return calendar_occupancy(typed_anchors(loaded, types), span=span, off_plan=off_plan)


def _churn_baseline(approved: PlanRevisionRecord | None) -> ChurnBaseline:
    """The revision churn is measured against, which is the last one the user approved.

    A week with no approved revision has none, and the baseline states that rather than naming
    a proposal nobody assented to. One that has one carries its PLAN as well as its name, because
    the term measures the difference between two documents and a name is not one.
    """
    if approved is None or approved.approved_at is None:
        return ChurnBaseline.never_approved()
    return ChurnBaseline.approved(approved.id, approved.approved_at, _baseline_plan(approved))


def _baseline_plan(approved: PlanRevisionRecord) -> PlanDocument | None:
    """The approved revision's plan, or nothing when this deployment cannot rebuild it.

    Degraded rather than raised, which is the opposite of what the live plan's reader does with
    the same refusal, and the difference is what each document is load-bearing for. Every netting
    rule reads the live plan, so a week whose plan of record cannot be rebuilt describes nothing
    and ``StoredPlacements`` refuses it. Churn is one term among the objective's others, and the
    baseline carries a third state saying its plan is unreadable with ``is_measured`` false in it,
    so a week whose APPROVED document cannot be rebuilt is solved with churn uncharged rather than
    not solved at all.
    """
    try:
        return plan_document(approved.document)
    except StoredDocumentCorrupt as refused:
        _log.warning(
            "plans.churn_baseline.unreadable",
            iso_week=str(approved.iso_week),
            revision_id=str(approved.id),
            refusal=str(refused),
        )
        return None


def _discretionary_minutes(
    span: Interval,
    *,
    frame: Sequence[FrameEntry],
    inherited: Sequence[Interval],
    calendar: CalendarOccupancy,
    off_plan: Sequence[OffPlanPeriod],
) -> int:
    """The week's denominator, which the proportional share of an Area's target is taken from.

    Each of the four subtrahends is read from whoever owns the question rather than assembled
    here: the frame's occupancy is this week's occurrences with the ones it inherited, and which
    windows leave the denominator is the calendar half's own reading of the subtraction table.

    Prep and transit BLOCKS are absent, and that is the narrowing the pure package states: they
    carry an Area, so they are discretionary time allocated to it in the same way a task is, and
    subtracting them would take the time out of the denominator AND charge it to an Area.
    """
    return discretionary_time(
        span,
        frame=frame_occupancy(frame, inherited),
        anchors=calendar.anchor_spans(),
        absolute_forbidden=calendar.absolute_forbidden(),
        off_plan=IntervalSet(period.interval for period in off_plan),
    )


def _adjustments(
    stored: Sequence[WeekAdjustmentRecord],
    candidate: WeekAdjustment | None,
    *,
    dates: Sequence[Date],
) -> tuple[WeekAdjustment, ...]:
    """Approved concessions, plus the one being evaluated. One list, so one code path folds them.

    The candidate goes last, so a concession being evaluated for a kind and target that already has
    a stored one is applied after it rather than instead of it, and the two compound. ``fold`` says
    so where the arithmetic is.
    """
    approved = tuple(_as_adjustment(record, dates=dates) for record in stored)
    return approved if candidate is None else (*approved, candidate)


def _as_adjustment(record: WeekAdjustmentRecord, *, dates: Sequence[Date]) -> WeekAdjustment:
    """One stored concession as the pure value the fold and a reason clause both read."""
    return WeekAdjustment(
        adjustment_id=record.id,
        kind=AdjustmentKind(record.kind),
        target_id=record.target_id,
        reductions=reductions_of(record.reductions, dates=dates),
        delta_minutes=record.delta_minutes,
    )
