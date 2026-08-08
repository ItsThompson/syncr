"""What the weekly session reads beyond the week view and the reviewed quarter.

Six questions, one read each, behind one method. The service that composes the payload asks for the
facts rather than for six repositories, so its constructor names the concerns it has rather than the
tables they live in, and this module is where the cost of the session's request is visible at once.

**Every reader belongs to the feature that owns its table.** The tasks are ``tasks``', the habits
are ``habits``' and their outcome log is plan storage's, the commitments are ``anchors``', and the
conflicts and the pins are plan storage's. A second reader of any of them would be a second answer
to a question a screen already asks.

**A commitment is NEW when the week before did not hold its series.** Two reads of one index rather
than a stored flag: an anchor carries no notion of being new, and a created-at instant would report
a commitment as new for as long as nobody had looked rather than for the week it lands in. A one-off
has no series and is therefore always new, which is right, because it cannot have been there last
week.

**The pins are read in the HOME zone, not the zone active on each pin's own date.** A promotion
candidate proposes a template entry, a template entry is declared as a wall time in the home zone,
and grouping in any other zone would offer the user a time their template cannot hold. That is why
``PinPlacement`` carries a zone at all, and it is the same reading the nightly run takes.

**The debt reading is taken over the log the raise is about, which is not one log.** A habit at its
cap is an ACCUMULATED figure and needs the whole log; an ``escalate`` habit is raised for a miss in
the week under review, because "raised in the next weekly session" is about the week that just
happened. Passing the whole log to an ``escalate`` habit raises it forever after one miss, which is
a nag rather than an escalation. So the log is chosen per policy, from one read, and the choice is
made here because this is where both logs exist."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.plans.conflicts import LIST_LIMIT
from syncr_domain.debt import debt_reading
from syncr_domain.habits import MissPolicy
from syncr_domain.promotion import PinPlacement
from syncr_domain.tasks import TaskStatus
from syncr_domain.weeks import week_span

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_api.anchors.records import AnchorRecord
    from syncr_api.anchors.repository import AnchorRepository
    from syncr_api.habits.outcome_log import HabitOutcomeReader
    from syncr_api.habits.records import HabitRecord
    from syncr_api.habits.repository import HabitRepository
    from syncr_api.plans.conflicts import PlanConflictRepository
    from syncr_api.plans.pins import PinRepository
    from syncr_api.plans.records import ConflictRecord
    from syncr_api.tasks.records import TaskRecord
    from syncr_api.tasks.repository import TaskRepository
    from syncr_domain.debt import DebtReading
    from syncr_domain.identifiers import HabitId
    from syncr_domain.intervals import Instant
    from syncr_domain.outcomes import HabitOutcome
    from syncr_domain.weeks import IsoWeek
    from syncr_domain.zones import ZoneId, ZoneProfile


@dataclass(frozen=True, slots=True, kw_only=True)
class SessionFacts:
    """Everything the session's raised items are derived from, read once.

    ``debt`` is keyed by habit and holds a reading for every habit, whether or not it is raised: the
    condition that decides a raise is ``syncr_domain.debt``'s and restating it here would be a
    second copy of the policy table."""

    open_tasks: tuple[TaskRecord, ...]
    habits: tuple[HabitRecord, ...]
    debt: Mapping[HabitId, DebtReading]
    arriving: tuple[AnchorRecord, ...]
    conflicts: tuple[ConflictRecord, ...]
    pins: tuple[PinPlacement, ...]


class SessionSources:
    """The six reads the weekly session takes beyond the week view and the reviewed quarter."""

    def __init__(
        self,
        *,
        tasks: TaskRepository,
        habits: HabitRepository,
        outcomes: HabitOutcomeReader,
        anchors: AnchorRepository,
        conflicts: PlanConflictRepository,
        pins: PinRepository,
    ) -> None:
        self._tasks = tasks
        self._habits = habits
        self._outcomes = outcomes
        self._anchors = anchors
        self._conflicts = conflicts
        self._pins = pins

    async def read(
        self,
        *,
        planned: IsoWeek,
        reviewed: Sequence[IsoWeek],
        profile: ZoneProfile,
        home_zone: ZoneId,
        now: Instant,
    ) -> SessionFacts:
        """Every fact the raises are derived from. Reads only, and writes nothing at all.

        ``reviewed`` is the history window oldest first, whose last member is the week the
        retrospective covers. The pins are read over the whole window and the commitments over two
        weeks of it, because a pattern is about weeks and a new commitment is about one boundary.
        """
        habits = await self._habits.list_all()
        log = await self._outcomes.read([habit.id for habit in habits])
        return SessionFacts(
            open_tasks=await self._tasks.list_all(status=TaskStatus.OPEN),
            habits=habits,
            debt=self._debt(habits, log, reviewed[-1], profile=profile, now=now),
            arriving=await self._arriving(planned, reviewed[-1], profile=profile),
            conflicts=await self._conflicts.list_all(limit=LIST_LIMIT),
            pins=await self._placements(reviewed, home_zone=home_zone),
        )

    def _debt(
        self,
        habits: Sequence[HabitRecord],
        log: Sequence[HabitOutcome],
        reviewed: IsoWeek,
        *,
        profile: ZoneProfile,
        now: Instant,
    ) -> Mapping[HabitId, DebtReading]:
        """One reading per habit, over the log its own policy's raise is about.

        The two logs are one read filtered two ways, so nothing is fetched twice and the two figures
        a reading carries are still stated over one set of outcomes, which is the precondition
        ``syncr_domain.debt`` states.
        """
        span = week_span(reviewed, profile)
        inside = [one for one in log if span.start <= one.occurred_at < span.end]
        readings = {}
        for habit in habits:
            about_the_week = habit.miss_policy is MissPolicy.ESCALATE
            outcomes = [
                one for one in (inside if about_the_week else log) if one.habit_id == habit.id
            ]
            readings[habit.id] = debt_reading(habit.as_habit(), outcomes, now)
        return readings

    async def _arriving(
        self, planned: IsoWeek, reviewed: IsoWeek, *, profile: ZoneProfile
    ) -> tuple[AnchorRecord, ...]:
        """The commitments the planned week holds that the reviewed week did not hold a series
        of."""
        landing = await self._anchors.overlapping(week_span(planned, profile))
        before = await self._anchors.overlapping(week_span(reviewed, profile))
        held = {one.series_uid for one in before if one.series_uid is not None}
        return tuple(one for one in landing if one.series_uid is None or one.series_uid not in held)

    async def _placements(
        self, weeks: Sequence[IsoWeek], *, home_zone: ZoneId
    ) -> tuple[PinPlacement, ...]:
        """The window's pins as the promotion rule reads them, in the tenant's home zone."""
        return tuple(
            PinPlacement(
                binding=pin.binding,
                iso_week=pin.iso_week,
                starts_at=pin.interval.start,
                zone=home_zone,
            )
            for pin in await self._pins.for_weeks(weeks)
        )
