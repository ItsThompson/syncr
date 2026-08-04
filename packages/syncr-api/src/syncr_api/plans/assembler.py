"""The week assembler: stored state in, one resolved ``SolveInputs`` out.

The widest integration point in the product. One method, three arguments, one return type, and
behind that interface every resolution the solver and the probe are deliberately spared. Their
purity is only possible because this component absorbs the impurity: the solver performs no
lookup, derives no domain projection, and reads no clock, so it is testable against literals.

## The pipeline, and the count that is load-bearing

**Fifteen resolutions over sixteen repository reads.** The figure is stated once, here, and the
bullets below are counted to match it, because a latency budget and an alert are calibrated to
it: an assembly is budgeted at p95 under 100 ms against reads on a warm cache, and the assembly
histogram's alert is read against that budget. Three of the fifteen are stubs today, each named
below with what it awaits.

```
assemble(iso_week, now, extra_adjustment=None)
  ├── resolve the week span, DST-correct, across a possible travel boundary
  ├── resolve each day's active zone
  ├── read the input version, from which the seed derives
  ├── name the churn baseline: the last approved revision, or never-approved
  ├── read what the week already holds: the live plan and its pins
  ├── load off-plan periods and clip them to the span
  ├── materialize routines: local target times to instants, at EFFECTIVE durations
  │     clamped to min_duration_minutes, one occurrence per day, each keyed by date
  ├── materialize template entries from the week pattern and the day types, keyed by date
  ├── expand habit cadence into occurrences, keyed by index in expansion order
  │     ├── derive each rotation cursor from the outcome log
  │     └── apply outstanding debt, capped
  ├── read the active weight set's duration multipliers, gated by maturity
  ├── collect eligible tasks, netting recorded minutes and IMMOVABLE placements only
  ├── compute the demand per deadline, netting EVERY placement falling before it
  ├── compute per-Area floor minutes, floor reservations, gross targets, and daily caps
  ├── resolve preferences down the Area to Habit or Task override chain, windows to instants
  └── FOLD approved concessions, plus a candidate when one is being evaluated,
        as a POST-PASS over the six resolved quantities above that they modify
```

**Folding is last and it is one code path.** Every quantity a concession changes is resolved
before it runs, so a reader asking what a concession touches reads one function rather than
tracing a pipeline. A candidate concession being evaluated is an argument rather than a table
read, which is what keeps a tradeoff request from persisting anything.

## Three resolutions await another component, and each is honest rather than absent

*Anchors, shadows, and forbidden windows* are the calendar half of this method and land in the
ticket that follows this one; the fields exist and are empty. *The live plan and its pins* come
through a reader whose production implementation answers with nothing, because no code names the
keys a stored binding holds yet. *The habit outcome log* is the same seam one module over.

Each is a seam rather than a silence: the netting rules, the cursor, and the debt figure are all
exercised through the real arithmetic in the suite, and bringing a reader online changes one line
of wiring.

## What this method never does

It reads no clock: ``now`` is stamped from its own argument, so an assembly is reproducible and a
caller can assemble against a past instant when reproducing a failure. It writes nothing at all,
not a row and not a version bump, so a read cannot change what the next solve sees. And it mints
no value a caller could supply wrongly: the seed is derived from the week and the input version on
read.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING

from prometheus_client import Histogram

from syncr_api.plans.cadence import habit_occurrences
from syncr_api.plans.demand import deadline_demands, eligible_tasks, task_demands
from syncr_api.plans.folding import Concessions, fold
from syncr_api.plans.materialization import (
    OffPlanSuppression,
    frame_entries,
    materialized_entries,
)
from syncr_api.plans.multipliers import DurationMultipliers
from syncr_api.plans.netting import PlacedTime, placements
from syncr_api.plans.reservations import area_budgets
from syncr_api.plans.resolved_preferences import area_caps, resolved_preferences
from syncr_api.user_settings.zone_reading import as_domain, zone_profile
from syncr_common.logging import get_logger
from syncr_common.metrics import REGISTRY, measured
from syncr_domain.discretionary import discretionary_time
from syncr_domain.intervals import Interval, IntervalSet
from syncr_domain.off_plan import OffPlanPeriod
from syncr_domain.plan import AdjustmentKind
from syncr_domain.weeks import active_zone_by_date, week_span
from syncr_solver.inputs import ChurnBaseline, SolveInputs, WeekAdjustment

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

    from syncr_api.areas.repository import AreaRepository
    from syncr_api.habits.outcome_log import HabitOutcomeReader
    from syncr_api.habits.repository import HabitRepository
    from syncr_api.learned.repository import WeightSetRepository
    from syncr_api.offplan.records import OffPlanPeriodRecord
    from syncr_api.offplan.repository import OffPlanPeriodRepository
    from syncr_api.plans.adjustments import WeekAdjustmentRepository
    from syncr_api.plans.placements import WeekPlacementReader
    from syncr_api.plans.records import PlanRevisionRecord, WeekAdjustmentRecord
    from syncr_api.plans.repository import PlanRepository
    from syncr_api.plans.versions import WeekInputVersionRepository
    from syncr_api.preferences.repository import PreferenceRepository
    from syncr_api.routines.repository import RoutineRepository
    from syncr_api.tasks.repository import TaskRepository
    from syncr_api.templates.repository import TemplateRepository, WeekPatternRepository
    from syncr_api.user_settings.repository import SettingsRepository, TravelOverrideRepository
    from syncr_domain.weeks import IsoWeek
    from syncr_domain.zones import Date
    from syncr_solver.inputs import FrameEntry

_log = get_logger("syncr.plans")

# How many resolutions the pipeline above performs, stated once so the docstring, the alert, and
# the latency budget read one figure. `test_week_assembler.py` counts the bullets against it.
RESOLUTION_COUNT = 15

# How many repository reads one assembly performs. The dominant cost of every request that
# returns a live verdict, which is what the assembly histogram exists to make visible.
REPOSITORY_READ_COUNT = 16

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

    Sixteen collaborators, and that is the component's nature rather than an accident: this is
    where every ounce of complexity the solver sheds actually lands. A caller cannot get it
    partially right, because there is nothing to get partially right.
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

        input_version = await self._versions.current(iso_week) or UNVERSIONED_WEEK
        churn_baseline = _churn_baseline(await self._revisions.latest_approved(iso_week))
        held = await self._placements.read(iso_week)
        placed = PlacedTime(placements(held.live_plan, held.pins, now=now), now=now)
        off_plan = _clipped_to(await self._off_plan.for_span(span), span)

        suppression = OffPlanSuppression(off_plan)
        frame = frame_entries(
            await self._routines.list_all(),
            dates=dates,
            zone_by_date=zone_by_date,
            off_plan=suppression,
        )
        template_entries = materialized_entries(
            pattern=await self._week_pattern.read(),
            templates=await self._templates.list_all(),
            dates=dates,
            zone_by_date=zone_by_date,
            off_plan=suppression,
        )

        habits = await self._habits.list_all()
        multipliers = DurationMultipliers.of(await self._weights.active())
        occurrences = habit_occurrences(
            habits,
            outcomes=await self._outcomes.read([habit.id for habit in habits]),
            now=now,
            multipliers=multipliers,
        )

        tasks = await self._tasks.list_all()
        stored_preferences = await self._preferences.list_all()
        declared_areas = await self._areas.list_all()
        resolved = Concessions(
            frame=frame,
            eligible_tasks=eligible_tasks(tasks, placed=placed, multipliers=multipliers),
            demands=task_demands(tasks, placed=placed, multipliers=multipliers),
            areas=area_budgets(
                declared_areas,
                discretionary_minutes=_discretionary_minutes(span, frame, off_plan),
                placed=placed,
                caps=area_caps(stored_preferences),
            ),
        )

        adjustments = _adjustments(await self._adjustments.for_week(iso_week), extra_adjustment)
        folded = fold(adjustments, resolved)

        inputs = SolveInputs(
            iso_week=iso_week,
            span=span,
            now=now,
            zone_by_date=zone_by_date,
            input_version=input_version,
            frame=folded.frame,
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
            pins=held.pins,
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
            template_entries=len(inputs.template_entries),
            habit_occurrences=len(inputs.habit_occurrences),
            eligible_tasks=len(inputs.eligible_tasks),
            deadline_demands=len(inputs.deadline_demands),
            adjustments=len(inputs.adjustments),
        )
        return inputs


def _churn_baseline(approved: PlanRevisionRecord | None) -> ChurnBaseline:
    """The revision churn is measured against, which is the last one the user approved.

    A week with no approved revision has none, and the baseline states that rather than naming
    a proposal nobody assented to.
    """
    if approved is None or approved.approved_at is None:
        return ChurnBaseline.never_approved()
    return ChurnBaseline.approved(approved.id, approved.approved_at)


def _clipped_to(
    periods: Sequence[OffPlanPeriodRecord], span: Interval
) -> tuple[OffPlanPeriod, ...]:
    """Every declared period, clipped to the week, in the order they were declared.

    Clipping loses nothing a figure reads: the denominator subtracts within the span anyway. What
    it buys is that a self-contained snapshot names no instant outside the week it describes, so a
    reader of the snapshot cannot derive a figure from a span the week does not hold.
    """
    clipped: list[OffPlanPeriod] = []
    for period in periods:
        inside = IntervalSet([period.interval]).clip(span)
        clipped.extend(
            OffPlanPeriod(interval=member, keep_frame=period.keep_frame, label=period.label)
            for member in inside
        )
    return tuple(clipped)


def _discretionary_minutes(
    span: Interval, frame: Sequence[FrameEntry], off_plan: Sequence[OffPlanPeriod]
) -> int:
    """The week's denominator, which the proportional share of an Area's target is taken from.

    Two of the four subtrahends are empty here and neither is forgotten: anchors and absolute
    forbidden windows arrive with the calendar resolutions, and the arithmetic takes them as sets
    so they flow in without this call changing.
    """
    return discretionary_time(
        span,
        frame=IntervalSet(entry.interval for entry in frame),
        anchors=IntervalSet(),
        absolute_forbidden=IntervalSet(),
        off_plan=IntervalSet(period.interval for period in off_plan),
    )


def _adjustments(
    stored: Sequence[WeekAdjustmentRecord], candidate: WeekAdjustment | None
) -> tuple[WeekAdjustment, ...]:
    """Approved concessions, plus the one being evaluated. One list, so one code path folds them.

    The candidate goes last, so a concession being evaluated for a kind and target that already
    has a stored one is applied after it rather than instead of it.
    """
    approved = tuple(_as_adjustment(record) for record in stored)
    return approved if candidate is None else (*approved, candidate)


def _as_adjustment(record: WeekAdjustmentRecord) -> WeekAdjustment:
    """One stored concession as the pure value the fold and a reason clause both read."""
    return WeekAdjustment(
        adjustment_id=record.id,
        kind=AdjustmentKind(record.kind),
        target_id=record.target_id,
        reductions=_reductions(record.reductions),
        delta_minutes=record.delta_minutes,
    )


def _reductions(stored: Mapping[str, object]) -> Mapping[Date, int]:
    """The per-date minutes a routine reduction carries, as dates rather than as stored keys.

    A key that is not a date or a value that is not a count of minutes is dropped and reported: a
    reduction nothing can pair with a frame occurrence would otherwise be applied to nothing while
    the concession claimed to have been honoured.
    """
    reductions: dict[Date, int] = {}
    unreadable: list[str] = []
    for key, value in stored.items():
        on = _a_date(key)
        if on is None or isinstance(value, bool) or not isinstance(value, int):
            unreadable.append(key)
            continue
        reductions[on] = value
    if unreadable:
        _log.warning("plans.adjustment.unreadable_reduction", entries=len(unreadable))
    return reductions


def _a_date(key: str) -> Date | None:
    try:
        return date.fromisoformat(key)
    except ValueError:
        return None
