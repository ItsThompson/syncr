"""The feasibility probe: capacity arithmetic that proves a week impossible and never possible.

Sorted interval algebra over roughly two hundred intervals, on the request path, so an
infeasibility surfaces while the user is still editing rather than after a solve lands. It
performs no search and no placement, which is exactly why it cannot prove the opposite: a week
whose totals are sufficient can still fail to pack, because capacity can exist in the wrong
shape. Every verdict from here therefore carries ``probe`` provenance and refuses the feasible
claim.

## The two spans, and why they are different

```
capacity  = span.after(now)      nothing before this instant can hold new work
denominator uses `span`          the whole week, so the budget report's figure is stable
```

The clip to ``now`` is what stops a past span being returned to capacity, and that is what
closes the hole where **not doing the work improved the verdict**. An outcome recorded on a past
block changes what is attributed to a task; it cannot change what is available, because the span
is already behind ``now``. Attribution and capacity are two rules, and conflating them inverts
the verdict.

## Free capacity is the denominator's own set, clipped

```
discretionary = span - union(frame, anchors, absolute_forbidden, off_plan)
free          = discretionary.after(now) - placed
```

Free capacity is derived from the denominator rather than computed beside it, so the two cannot
subtract different sets: a change to what leaves the denominator moves both figures or neither.
**A scoped window is in neither**, because it is capacity for every Area it does not name, and
subtracting it from a whole-week figure manufactures a shortfall that does not exist. It bites in
the two per-Area readings, which subtract the windows naming that Area and nothing else.

## Three checks, and what each compares

| Check | Compares | Reports |
|---|---|---|
| the floors against the week | every reservation, summed, against free | `floors_exceed_capacity` |
| a demand against its deadline | work due before an instant against that | `deadline_capacity` |
| a floor against its own Area | one reservation against what it claims | `area_floor_unreachable` |

Both sides of every comparison count **one** placement set. The reservations and the demands
arrive net of every placement, pinned or not, and free capacity subtracts every placement, so a
pinned hour is subtracted once rather than charged twice. That symmetry is the whole reason
progress cannot manufacture a shortfall.

**A floor is not a competitor for the capacity its own Area's deadline needs.** Work placed for a
Career task lands in the Career Area and satisfies the Career floor, so the deadline check
reserves the OTHER Areas' floors and the per-Area check counts the OTHER Areas' demands. Counting
an Area's own floor against its own deadline charges one requirement twice, and it is what would
make pinning work toward a deadline improve that deadline's own reading.

**And only the part of those floors that cannot fit after the deadline is reserved.** A five-hour
Fitness floor with sixty hours of the week left after Tuesday competes with nothing on Tuesday.
Reserving the whole of every floor against every deadline inflates each deadline's gap by every
floor the week has not yet scheduled, which reports a shortfall on a fresh week that has room for
everything. The capacity after a deadline is read over the whole week's free capacity rather than
per Area, which is an upper bound on what the floors can absorb later, so the reserved figure is
a lower bound: this check under-reports rather than over-reports, which is the only direction a
necessary-condition test may err in.

**A competitor's whole-week figure is discounted before it meets a per-Area capacity set.** Both
per-Area checks compare a figure from other Areas against the capacity THIS Area may claim, and the
moment a scoped window names this Area the two are over different sets: its capacity has the window
removed and the other Areas' work does not have to avoid it. So the figure is reduced by the
capacity the others may use and this one may not, which is what keeps a week holding a valid
assignment from reporting a gap. The discount is optimistic about where the other work lands, and
that is deliberately the same direction as the reservation above.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.discretionary import discretionary_intervals
from syncr_domain.feasibility.verdict import (
    Provenance,
    Shortfall,
    ShortfallKind,
    Verdict,
    hours_and_minutes,
)
from syncr_domain.intervals import IntervalSet

if TYPE_CHECKING:
    from syncr_domain.feasibility.inputs import DeadlineDemand, ProbeInputs
    from syncr_domain.identifiers import AreaId
    from syncr_domain.intervals import Instant


def probe(inputs: ProbeInputs) -> Verdict:
    """Prove ``inputs`` infeasible from capacity arithmetic, and quantify every gap found.

    Pure, deterministic, and sub-millisecond at realistic sizes: the same inputs give the same
    verdict, including the order of the shortfalls. Finding none means the week could not be
    proven impossible, which is a weaker statement than the week being possible, and
    ``Verdict.feasible`` stays false to keep the two from being read as one.
    """
    week = _Week.of(inputs)
    return Verdict(
        feasible=False,
        provenance=Provenance.PROBE,
        computed_at=inputs.computed_at,
        input_version=inputs.input_version,
        discretionary_minutes=week.discretionary.total_minutes(),
        shortfalls=(
            *_floors_against_the_week(week),
            *_demands_against_their_deadlines(week),
            *_floors_against_their_own_areas(week),
        ),
    )


@dataclass(frozen=True, slots=True)
class _Week:
    """One week's capacity, derived once and read by all three checks.

    Derived here rather than per check because two of the three would otherwise each state the
    union of the occupancy, and two statements of that union is how the verdict panel and the
    budget report come to disagree about the same week.
    """

    inputs: ProbeInputs
    discretionary: IntervalSet
    free: IntervalSet
    honoring: tuple[str, ...]

    @classmethod
    def of(cls, inputs: ProbeInputs) -> _Week:
        discretionary = discretionary_intervals(
            inputs.span,
            frame=inputs.frame,
            anchors=inputs.anchors,
            absolute_forbidden=inputs.absolute_forbidden,
            off_plan=inputs.off_plan,
        )
        return cls(
            inputs=inputs,
            discretionary=discretionary,
            free=discretionary.after(inputs.now).subtract(inputs.placed),
            honoring=_occupancy_honored(inputs),
        )

    def free_for(self, area_id: AreaId) -> IntervalSet:
        """What one Area may still claim: free capacity less the windows that name it."""
        return self.free.subtract(self.inputs.scoped_against(area_id))


def _floors_against_the_week(week: _Week) -> tuple[Shortfall, ...]:
    """Every reservation together against the capacity the week has left.

    Both sides are net, so no committed minute is counted twice: a floor already met by placed
    blocks reserves that much less, and the blocks that met it are already out of free capacity.
    """
    reservations = week.inputs.area_floor_reservations
    reserved = sum(reservation.reserved_minutes for reservation in reservations)
    available = week.free.total_minutes()
    if reserved <= available:
        return ()
    return (
        Shortfall(
            kind=ShortfallKind.FLOORS_EXCEED_CAPACITY,
            minutes=reserved - available,
            against=tuple(
                reservation.label for reservation in reservations if reservation.reserved_minutes
            ),
            honoring=(
                *week.honoring,
                f"the {hours_and_minutes(available)} still uncommitted this week",
            ),
        ),
    )


def _demands_against_their_deadlines(week: _Week) -> tuple[Shortfall, ...]:
    """Each deadline's work against the capacity its Area has before it, earliest deadline first.

    ``claimed`` accumulates what the earlier deadlines took, so two tasks sharing one deadline
    are not each told the whole capacity is theirs, and a Tuesday deadline consumes the hours a
    Friday one would otherwise count on. It is a whole-week figure, so it is discounted by the
    capacity those earlier deadlines may use and this Area may not before the two meet.

    A deadline at or before ``now`` has zero capacity and its whole remaining demand is the gap,
    which is correct rather than degenerate: work due yesterday that is not done cannot be fitted
    anywhere.
    """
    found: list[Shortfall] = []
    claimed = 0
    claimed_labels: list[str] = []
    for demand in sorted(week.inputs.deadline_demands, key=_earliest_first):
        claimable = week.free_for(demand.area_id).before(demand.deadline)
        reserved = _reserved_before(week, demand.deadline, for_area=demand.area_id)
        # One discount over both competitors together, because they compete for the same capacity:
        # discounting each separately would credit this Area twice with the same minutes it cannot
        # use.
        competing = _competing_minutes(
            claimed + reserved.minutes,
            claimable=claimable,
            jointly=week.free.before(demand.deadline),
        )
        capacity = claimable.total_minutes()
        available = max(0, capacity - competing)
        if available < demand.remaining_minutes:
            found.append(
                Shortfall(
                    kind=ShortfallKind.DEADLINE_CAPACITY,
                    minutes=demand.remaining_minutes - available,
                    against=demand.labels,
                    deadline=demand.deadline,
                    area_id=demand.area_id,
                    honoring=(
                        *reserved.labels,
                        *claimed_labels,
                        *week.honoring,
                        f"the {hours_and_minutes(capacity)} still uncommitted before it",
                    ),
                )
            )
        claimed += min(available, demand.remaining_minutes)
        claimed_labels.extend(f"{label}, due no later than this" for label in demand.labels)
    return tuple(found)


def _floors_against_their_own_areas(week: _Week) -> tuple[Shortfall, ...]:
    """Each reservation against what its own Area may claim, after the other Areas' deadlines.

    This is where a scoped window bites: it reduces capacity for the Areas it names and for no
    others, so an Area forbidden from every recovery window in a heavy week can be unable to
    reach a floor the week as a whole has room for. The other Areas' demands are a whole-week
    figure, so they are discounted by the capacity they may use and this Area may not.
    """
    demands = week.inputs.deadline_demands
    found: list[Shortfall] = []
    for reservation in week.inputs.area_floor_reservations:
        if not reservation.reserved_minutes:
            continue
        claimable = week.free_for(reservation.area_id)
        elsewhere = tuple(demand for demand in demands if demand.area_id != reservation.area_id)
        demanded = sum(demand.remaining_minutes for demand in elsewhere)
        competing = _competing_minutes(demanded, claimable=claimable, jointly=week.free)
        available = max(0, claimable.total_minutes() - competing)
        if reservation.reserved_minutes <= available:
            continue
        found.append(
            Shortfall(
                kind=ShortfallKind.AREA_FLOOR_UNREACHABLE,
                minutes=reservation.reserved_minutes - available,
                against=(reservation.label,),
                area_id=reservation.area_id,
                honoring=(
                    *_demand_labels(elsewhere),
                    *week.honoring,
                    f"the {hours_and_minutes(claimable.total_minutes())} "
                    f"{reservation.label} may still claim",
                ),
            )
        )
    return tuple(found)


@dataclass(frozen=True, slots=True)
class _Reserved:
    """How much of the other Areas' floors has to come out of the capacity before one deadline.

    The labels are empty when the figure is, so a shortfall never honors a floor that took
    nothing from it.
    """

    minutes: int
    labels: tuple[str, ...]


def _reserved_before(week: _Week, deadline: Instant, *, for_area: AreaId) -> _Reserved:
    """The floors that must eat into the capacity before ``deadline``, and their names.

    An Area's own floor is not among them: work placed for that Area's deadline satisfies that
    Area's floor, so reserving it here would charge one requirement twice and would make pinning
    work toward the deadline improve the very reading it is measured by.
    """
    others = tuple(
        reservation
        for reservation in week.inputs.area_floor_reservations
        if reservation.area_id != for_area and reservation.reserved_minutes
    )
    reserved = sum(reservation.reserved_minutes for reservation in others)
    absorbed_later = week.free.after(deadline).total_minutes()
    minutes = max(0, reserved - absorbed_later)
    if not minutes:
        return _Reserved(minutes=0, labels=())
    return _Reserved(
        minutes=minutes,
        labels=tuple(
            f"the {reservation.label} floor of {hours_and_minutes(reservation.reserved_minutes)}"
            for reservation in others
        ),
    )


def _competing_minutes(minutes: int, *, claimable: IntervalSet, jointly: IntervalSet) -> int:
    """How much of another Area's work really competes for the capacity this Area may claim.

    The two per-Area checks each compare a whole-week figure from OTHER Areas against a per-Area
    capacity set, and the moment a scoped window names this Area the two are over different sets:
    this Area's capacity has the window removed and the other Areas' work does not have to avoid
    it. Charging the whole figure here reports a gap on a week where a valid assignment exists,
    which is the one direction capacity arithmetic may not err in.

    So the figure is discounted by the capacity the others may use and this Area may not. That is
    optimistic about where the other work lands, which is the safe direction: the result is a lower
    bound on the competition and therefore an upper bound on what is available. With no scoped
    window naming this Area the discount is zero and this is the whole figure, unchanged.

    Every competitor passes through here as ONE figure, because they compete for one set of
    minutes: discounting two of them separately would credit this Area twice with the capacity it
    cannot use.
    """
    elsewhere_only = jointly.subtract(claimable).total_minutes()
    return max(0, minutes - elsewhere_only)


def _occupancy_honored(inputs: ProbeInputs) -> tuple[str, ...]:
    """What the week has already spent inside the capacity window, named for the user.

    Only a term that overlaps that window is named: occupancy entirely behind ``now`` took
    nothing from the capacity this check measured, so honoring it would name a constraint that
    did not produce the gap.
    """
    capacity = IntervalSet([inputs.span]).after(inputs.now)
    stated = (
        ("the circadian frame", inputs.frame),
        ("your external commitments", inputs.anchors),
        ("the time reserved around them", inputs.absolute_forbidden),
        ("the days you declared off-plan", inputs.off_plan),
        ("the time already committed to this week's plan", inputs.placed),
    )
    return tuple(label for label, occupied in stated if occupied.intersect(capacity))


def _demand_labels(demands: tuple[DeadlineDemand, ...]) -> tuple[str, ...]:
    """The tasks a set of demands names, deduplicated in order, for a honored-constraint list."""
    named: dict[str, None] = {}
    for demand in demands:
        for label in demand.labels:
            named.setdefault(label, None)
    return tuple(named)


def _earliest_first(demand: DeadlineDemand) -> tuple[Instant, str, tuple[str, ...]]:
    """A total order over demands: earliest deadline, then Area, then the tasks it names.

    Total rather than by deadline alone, because the accumulation makes the order observable and
    two demands sharing one instant must be consumed in one order on every run.
    """
    return (demand.deadline, str(demand.area_id), demand.labels)
