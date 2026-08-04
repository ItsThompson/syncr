"""Resolving a declared wall time into instants, once per date of the week.

Two shapes declare a time of day and a duration and materialize one occurrence per date: a
routine, which is the circadian frame, and a template entry, which is a day shape's part. Both
are FIXED BY DERIVATION: nothing downstream moves them, so what this module emits is the search
space rather than a candidate inside it.

## The rules that are the same for both

*A target time is wall time.* ``Wake 05:00`` means 05:00 wherever the user is, so each date
resolves its own zone. A spring-forward gap shifts a target forward by the gap and a fall-back
repeat takes the first occurrence, both through
:func:`syncr_domain.zones.to_instant`, which is the one implementation of either rule.

*A duration is ELAPSED minutes.* Eight hours of sleep is eight hours on every night of the year,
so a transition inside an occurrence moves its wall-clock end rather than its length. Read as
wall-clock arithmetic instead, one night would be seven real hours and another nine, which would
silently spend a sleep floor the solver is forbidden to spend.

*An occurrence is keyed by its local date and is never clipped.* A Sunday ``Sleep 23:00 + 8h``
belongs to the week its START falls in and keeps its whole duration. Clipping it would report a
duration the routine does not have, and duplicating it into the following week would give one
night two blocks.

## Off-plan periods suppress by OVERLAP, and what suppression means differs by shape

A period declares that nothing materializes inside it, and ``keep_frame`` says whether routines
are the exception. An occurrence that overlaps a period is suppressed whole rather than clipped
to the part outside it: clipping changes the span an outcome is keyed against, and the rule is
about what may sit inside the span rather than about how long a block is.

A template entry is content, so any period suppresses it. A routine is the frame, so only a
period whose ``keep_frame`` is false does. Which periods a week holds is :func:`periods_of`,
because an assembly resolves two weeks and each occurrence is judged against the periods of the
week that owns it.

## An occurrence can overlap its own next one, and no bound can stop it

A routine of more than a local day overlaps the next date's occurrence, and no positive duration
cap expresses otherwise: a spring-forward local day is 23 hours, so 1381 minutes already
overlaps on that date, and a date a zone skips entirely gives two dates the same interval at
every duration. **Both occurrences are emitted.** Two frame blocks overlapping is a state the
grid draws with no special case, and each date keys its own block, so dropping either would lose
a key an outcome may already reference.

## A concrete entry arrives named and charged, or it does not arrive

A block carries the resolved content name and, unless it is the frame or an anchor, an Area. An
entry declares neither: it names a routine or a habit, and both live in tables this module is
handed. So a concrete entry is resolved against those rows HERE rather than joined out of the
snapshot later, because no join inside the snapshot is total: a habit's occurrences are
cadence-filtered, so an entry naming a habit that is not due this week would find no name at all.

An entry whose content is missing, or whose Area resolves to nothing, is DROPPED and counted. Both
are producer defects rather than states of the week: a binding naming no row this tenant has,
which the entry boundary does not yet refuse, and a concrete entry naming a routine while
declaring no Area, which no block can carry because a routine has none. Dropping is the
degradation an anchor carrying an unread type already takes: the rest of the week assembles, and
refusing would fail every solve, pin, and live verdict for the week over one malformed row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from syncr_common.logging import get_logger
from syncr_domain.identity import date_occurrence_key
from syncr_domain.intervals import Interval, IntervalSet
from syncr_domain.off_plan import OffPlanPeriod
from syncr_domain.templates import BindingTarget, TemplateEntryKind
from syncr_domain.weeks import Weekday
from syncr_domain.zones import to_instant
from syncr_solver.inputs import EntryBinding, FrameEntry, MaterializedEntry

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from uuid import UUID

    from syncr_api.habits.records import HabitRecord
    from syncr_api.offplan.records import OffPlanPeriodRecord
    from syncr_api.routines.records import RoutineRecord
    from syncr_api.templates.records import TemplateEntryRecord, TemplateRecord
    from syncr_domain.identifiers import AreaId, DayTypeId
    from syncr_domain.templates import WeekPattern
    from syncr_domain.zones import Date, LocalTime, ZoneId

_log = get_logger("syncr.plans")


def periods_of(periods: Sequence[OffPlanPeriodRecord], span: Interval) -> tuple[OffPlanPeriod, ...]:
    """Every declared period, clipped to one week's span, in the order they were declared.

    Clipping loses nothing a figure reads: the denominator subtracts within the span anyway. What
    it buys is that a self-contained snapshot names no instant outside the week it describes, so a
    reader of the snapshot cannot derive a figure from a span the week does not hold.

    Stated here rather than in the assembler because two weeks are read per assembly: the week
    being assembled, and the one before it whose boundary-crossing occurrences it inherits. A
    second statement of this is how the inherited occurrence would come to be suppressed by a
    period its own week does not hold.
    """
    clipped: list[OffPlanPeriod] = []
    for period in periods:
        inside = period.interval.clipped_to(span)
        if inside is None:
            continue
        clipped.append(
            OffPlanPeriod(interval=inside, keep_frame=period.keep_frame, label=period.label)
        )
    return tuple(clipped)


class OffPlanSuppression:
    """Which spans a week's off-plan periods keep empty, per kind of occurrence.

    Two sets rather than one predicate with a flag, because the question a caller asks is not
    "is this off-plan" but "may THIS kind of thing materialize here", and the two answers differ
    on exactly the periods that keep the frame.
    """

    __slots__ = ("_content", "_frame")

    def __init__(self, periods: Sequence[OffPlanPeriod]) -> None:
        self._content = IntervalSet(period.interval for period in periods)
        self._frame = IntervalSet(period.interval for period in periods if not period.keep_frame)

    def suppresses_content(self, interval: Interval) -> bool:
        """Whether a template entry, which is content, may not materialize here."""
        return self._content.overlaps(interval)

    def suppresses_the_frame(self, interval: Interval) -> bool:
        """Whether a routine may not materialize here, which ``keep_frame`` decides."""
        return self._frame.overlaps(interval)


def effective_duration_minutes(
    *, duration_minutes: int, min_duration_minutes: int, reduction_minutes: int = 0
) -> int:
    """R6: one occurrence's duration after any approved reduction, clamped to its floor.

    The clamp is a domain validation on the assembler rather than a solver constraint, because
    no solver operation resizes a routine: the frame arrives already resolved. The sleep floor
    is this clamp on the sleep routine and there is no sleep-specific rule anywhere.

    Stated here and called on both paths, the base resolution and the fold, so a reduction and
    an unreduced occurrence cannot be clamped by two different readings of one rule.
    """
    return max(min_duration_minutes, duration_minutes - reduction_minutes)


def frame_entries(
    routines: Sequence[RoutineRecord],
    *,
    dates: Sequence[Date],
    zone_by_date: Mapping[Date, ZoneId],
    off_plan: OffPlanSuppression,
) -> tuple[FrameEntry, ...]:
    """One occurrence per routine per date, at its effective duration, keyed by that date.

    Emitted in date order and then in the routines' own order, which is the order the day runs,
    so two assemblies of unchanged declarations emit one sequence.
    """
    resolved: list[FrameEntry] = []
    for on in dates:
        zone = zone_by_date[on]
        for routine in routines:
            span = routine.as_span()
            minutes = effective_duration_minutes(
                duration_minutes=span.duration_minutes,
                min_duration_minutes=span.min_duration_minutes,
            )
            interval = _occurrence(span.target_time, on, zone, minutes)
            if off_plan.suppresses_the_frame(interval):
                continue
            resolved.append(
                FrameEntry(
                    routine_id=routine.id,
                    occurrence_key=date_occurrence_key(on),
                    interval=interval,
                    min_duration_minutes=span.min_duration_minutes,
                    flex_band_minutes=span.flex_band_minutes,
                    title=routine.title,
                )
            )
    return tuple(resolved)


def reduced_frame_entry(entry: FrameEntry, *, reduction_minutes: int) -> FrameEntry:
    """``entry`` shortened by an approved reduction, clamped to its own floor.

    The start does not move. A reduction is a concession about how long a routine runs, not
    about when it begins, and the flex band is what moves a target time.
    """
    minutes = effective_duration_minutes(
        duration_minutes=entry.interval.total_minutes(),
        min_duration_minutes=entry.min_duration_minutes,
        reduction_minutes=reduction_minutes,
    )
    return FrameEntry(
        routine_id=entry.routine_id,
        occurrence_key=entry.occurrence_key,
        interval=Interval(entry.interval.start, entry.interval.start + timedelta(minutes=minutes)),
        min_duration_minutes=entry.min_duration_minutes,
        flex_band_minutes=entry.flex_band_minutes,
        title=entry.title,
    )


def materialized_entries(
    *,
    pattern: WeekPattern | None,
    templates: Sequence[TemplateRecord],
    routines: Sequence[RoutineRecord],
    habits: Sequence[HabitRecord],
    dates: Sequence[Date],
    zone_by_date: Mapping[Date, ZoneId],
    off_plan: OffPlanSuppression,
) -> tuple[MaterializedEntry, ...]:
    """Each weekday's day shape, resolved for that weekday's date, its content named.

    A tenant who has declared no week pattern materializes nothing, which is the first-run state
    rather than an error: a pattern maps all seven weekdays or it is not a pattern, so there is
    no partial mapping to interpret. A day type whose shape has no entries materializes nothing
    for the same reason.
    """
    if pattern is None:
        return ()
    by_day_type = _templates_by_day_type(templates)
    content = _content_by_binding(routines, habits)
    resolved: list[MaterializedEntry] = []
    unresolved: list[str] = []
    for on in dates:
        template = by_day_type.get(pattern.day_type(_weekday_of(on)))
        if template is None:
            continue
        zone = zone_by_date[on]
        for stored in template.entries:
            entry = _entry_on(stored, on, zone, off_plan, content, unresolved)
            if entry is not None:
                resolved.append(entry)
    _report(unresolved)
    return tuple(resolved)


@dataclass(frozen=True, slots=True)
class EntryContent:
    """What a concrete entry's binding names: the title a block carries, and its Area.

    A routine has no Area, because the frame is not a category competing with Fitness. An entry
    naming one therefore has to declare an Area of its own, and the block it becomes carries
    that one.
    """

    title: str
    area_id: AreaId | None = None


def _content_by_binding(
    routines: Sequence[RoutineRecord], habits: Sequence[HabitRecord]
) -> Mapping[tuple[BindingTarget, UUID], EntryContent]:
    """Every row a concrete entry may name, keyed by the pair that names it.

    Keyed by the target as well as the identifier, so an entry whose target says ``habit`` cannot
    resolve against a routine that happens to share an identifier. That is the whole reason the
    target column exists: the two live in separate tables with no shared parent.
    """
    routine_content = {
        (BindingTarget.ROUTINE, routine.id): EntryContent(title=routine.title)
        for routine in routines
    }
    habit_content = {
        (BindingTarget.HABIT, habit.id): EntryContent(title=habit.title, area_id=habit.area_id)
        for habit in habits
    }
    return routine_content | habit_content


def _entry_on(
    stored: TemplateEntryRecord,
    on: Date,
    zone: ZoneId,
    off_plan: OffPlanSuppression,
    content: Mapping[tuple[BindingTarget, UUID], EntryContent],
    unresolved: list[str],
) -> MaterializedEntry | None:
    interval = _occurrence(stored.span.target_time, on, zone, stored.span.duration_minutes)
    if off_plan.suppresses_content(interval):
        return None
    binding = _content_of(stored)
    charged = _charged(stored, binding, content, unresolved)
    if charged is None:
        return None
    return MaterializedEntry(
        entry_id=stored.id,
        occurrence_key=date_occurrence_key(on),
        kind=stored.kind,
        interval=interval,
        flex_band_minutes=stored.span.flex_band_minutes,
        area_id=charged.area_id,
        title=charged.title,
        binding=binding,
    )


@dataclass(frozen=True, slots=True)
class _Charged:
    """What the block an entry becomes is called, and which Area its minutes are charged to."""

    area_id: AreaId
    title: str | None = None


def _charged(
    stored: TemplateEntryRecord,
    binding: EntryBinding | None,
    content: Mapping[tuple[BindingTarget, UUID], EntryContent],
    unresolved: list[str],
) -> _Charged | None:
    """The title and the Area the block this entry becomes carries, or nothing.

    A slot carries its declared Area and no title, because nothing has been chosen to name yet.
    A concrete entry carries its content's name, and its content's Area unless the content has
    none, in which case its own declaration is what the minutes are charged to.

    Returning nothing is the drop, and each cause is recorded so an assembly that quietly lost
    part of a day shape can say which row cost it.
    """
    if stored.kind is not TemplateEntryKind.CONCRETE:
        if stored.area_id is None:
            unresolved.append("slot_without_an_area")
            return None
        return _Charged(area_id=stored.area_id)
    if binding is None:
        unresolved.append("concrete_without_a_binding")
        return None
    found = content.get((binding.target, binding.entity_id))
    if found is None:
        unresolved.append("content_this_tenant_does_not_have")
        return None
    area_id = found.area_id or stored.area_id
    if area_id is None:
        unresolved.append("content_with_no_area_and_none_declared")
        return None
    return _Charged(area_id=area_id, title=found.title)


def _report(unresolved: Sequence[str]) -> None:
    """Say once how many entries this assembly dropped, and per cause.

    Counted rather than named one line per entry, which is how a template every date shares turns
    one malformed row into seven log lines.
    """
    if not unresolved:
        return
    counted = {cause: unresolved.count(cause) for cause in sorted(set(unresolved))}
    _log.warning(
        "plans.assembly.template_entry_unresolved",
        entries_dropped=len(unresolved),
        by_cause=counted,
    )


def _content_of(stored: TemplateEntryRecord) -> EntryBinding | None:
    """What a concrete entry names, and nothing for a slot, whose content is bound late."""
    if stored.kind is not TemplateEntryKind.CONCRETE:
        return None
    if stored.binding_target is None or stored.binding_ref is None:
        return None
    return EntryBinding(target=stored.binding_target, entity_id=stored.binding_ref)


def _templates_by_day_type(
    templates: Sequence[TemplateRecord],
) -> Mapping[DayTypeId, TemplateRecord]:
    """The shape declared for each day type. One per type, which the table enforces."""
    return {template.day_type_id: template for template in templates}


def _weekday_of(on: Date) -> Weekday:
    """Which weekday a date is, in the enum's own ISO order rather than by a stored number."""
    return tuple(Weekday)[on.weekday()]


def _occurrence(target_time: LocalTime, on: Date, zone: ZoneId, minutes: int) -> Interval:
    """The instant a declared wall time names on ``on``, plus ``minutes`` of ELAPSED time."""
    start = to_instant(target_time, on, zone)
    return Interval(start, start + timedelta(minutes=minutes))
