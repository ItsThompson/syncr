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
from syncr_domain.feasibility.honoring import (
    demands_due_no_later,
    demands_honored,
    floor_honored,
    occupancy_honored,
)
from syncr_domain.feasibility.verdict import (
    Provenance,
    Shortfall,
    ShortfallKind,
    Verdict,
    hours_and_minutes,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_domain.feasibility.inputs import DeadlineDemand, FloorReservation, ProbeInputs
    from syncr_domain.identifiers import AreaId
    from syncr_domain.intervals import Instant, IntervalSet


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
            honoring=occupancy_honored(inputs),
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

    ``claimed`` accumulates what the earlier deadlines took, PER AREA, so two tasks sharing one
    deadline are not each told the whole capacity is theirs, and a Tuesday deadline consumes the
    hours a Friday one would otherwise count on. Per Area rather than as one total because an
    Area's earlier work and its own floor are the same minutes: see :func:`_competition_before`.

    A deadline at or before ``now`` has zero capacity and its whole remaining demand is the gap,
    which is correct rather than degenerate: work due yesterday that is not done cannot be fitted
    anywhere.
    """
    found: list[Shortfall] = []
    claimed: dict[AreaId, int] = {}
    claimed_labels: list[str] = []
    for demand in sorted(week.inputs.deadline_demands, key=_earliest_first):
        claimable = week.free_for(demand.area_id).before(demand.deadline)
        competition = _competition_before(
            week, demand.deadline, for_area=demand.area_id, claimed=claimed
        )
        # One discount over the whole competition, because every competitor is after the same
        # capacity: discounting each separately would credit this Area twice with the same minutes
        # it cannot use.
        competing = _competing_minutes(
            competition.minutes,
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
                        *competition.labels,
                        *claimed_labels,
                        *week.honoring,
                        f"the {hours_and_minutes(capacity)} still uncommitted before it",
                    ),
                )
            )
        claimed[demand.area_id] = claimed.get(demand.area_id, 0) + min(
            available, demand.remaining_minutes
        )
        claimed_labels.extend(demands_due_no_later(demand))
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
                    *demands_honored(elsewhere),
                    *week.honoring,
                    f"the {hours_and_minutes(claimable.total_minutes())} "
                    f"{reservation.label} may still claim",
                ),
            )
        )
    return tuple(found)


@dataclass(frozen=True, slots=True)
class _Competition:
    """What the other Areas must place before one deadline, and the constraints that say so.

    The labels are empty when the figure is, so a shortfall never honors a floor that took nothing
    from it. A floor is named at its DECLARED size rather than at the part of it that had to come
    early: the constraint the user holds is the whole floor, and apportioning it would state a split
    nothing computed.
    """

    minutes: int
    labels: tuple[str, ...]


def _competition_before(
    week: _Week, deadline: Instant, *, for_area: AreaId, claimed: Mapping[AreaId, int]
) -> _Competition:
    """The minutes other work must take from the capacity before ``deadline``, and its names.

    **Per Area, the LARGER of two figures rather than their sum, because they are the same
    minutes.** A block placed for a Career task lands in the Career Area, so it satisfies the Career
    task and the Career floor together: an Area owing 2h by Wednesday against an unmet 5h floor has
    to place 5h, not 7h. Adding them invents work the week does not owe and reports a gap on a week
    that holds a valid assignment, which is the one direction this arithmetic may not take.

    The two figures per Area are what its earlier deadlines already claimed, and the part of its
    floor that cannot fit after this deadline. The capacity that could absorb a floor later is read
    over the whole week's free capacity rather than per Area, which is an upper bound on what can be
    absorbed and therefore keeps this figure a lower bound.

    **The measured Area's own floor is excluded and its own earlier demands are not.** The floor is
    excluded for the reason above, one step nearer: this demand's own work satisfies it. Its earlier
    demands are not, because two deadlines in one Area really do need two lots of minutes.
    """
    absorbed_later = week.free.after(deadline).total_minutes()
    reserved_by_area = {
        reservation.area_id: reservation
        for reservation in week.inputs.area_floor_reservations
        if reservation.reserved_minutes
    }
    minutes = claimed.get(for_area, 0)
    labels: list[str] = []
    for area_id in _competing_areas(reserved_by_area, claimed, for_area=for_area):
        reservation = reserved_by_area.get(area_id)
        early = 0 if reservation is None else max(0, reservation.reserved_minutes - absorbed_later)
        minutes += max(claimed.get(area_id, 0), early)
        if early and reservation is not None:
            labels.append(
                floor_honored(
                    label=reservation.label, reserved_minutes=reservation.reserved_minutes
                )
            )
    return _Competition(minutes=minutes, labels=tuple(labels))


def _competing_areas(
    reserved_by_area: Mapping[AreaId, FloorReservation],
    claimed: Mapping[AreaId, int],
    *,
    for_area: AreaId,
) -> tuple[AreaId, ...]:
    """Every Area with something to place besides the one being measured, in a stable order.

    The reservations' own order first, then any Area that owes an earlier deadline and no floor, so
    two probes of one week name the honored floors in one order.
    """
    ordered = [area_id for area_id in reserved_by_area if area_id != for_area]
    ordered += [
        area_id for area_id in claimed if area_id != for_area and area_id not in reserved_by_area
    ]
    return tuple(ordered)


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


def _earliest_first(demand: DeadlineDemand) -> tuple[Instant, str, tuple[str, ...]]:
    """A total order over demands: earliest deadline, then Area, then the tasks it names.

    Total rather than by deadline alone, because the accumulation makes the order observable and
    two demands sharing one instant must be consumed in one order on every run.
    """
    return (demand.deadline, str(demand.area_id), demand.labels)
