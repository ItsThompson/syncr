"""What the probe reads, and the question every one of its fields answers.

This struct is a **pure projection** of a solve input rather than a second assembly. There is
one producer, the week assembler, and ``SolveInputs.for_probe()`` splits the forbidden windows
by scope, flattens the typed collections into interval sets, and carries the already-net demands
and reservations forward verbatim. It computes no netting: the assembler did that, and
re-deriving it here is the one mistake this projection must not make.

## Every field, and the question it answers

The struct needed an arithmetic correction in four consecutive reviews, and the root cause was
never the arithmetic. It was that fields were named after concepts that changed elsewhere without
this struct being revisited. So each field is defined against the question it exists to answer,
and each names where its definition lives. **The table is the drift-catcher: a field with no row
is the failure mode the table exists to prevent**, and a test asserts the two sets are equal.

| Field | The question it answers | Defined by |
|---|---|---|
| `span` | over what period is the DENOMINATOR taken? the whole week | `syncr_domain.weeks` |
| `now` | from when is CAPACITY available? nothing earlier holds work | this module |
| `computed_at` | what instant does the verdict claim? | this module |
| `input_version` | which assembly is that verdict about? | `syncr_api.plans.versions` |
| `frame` | what does the circadian frame occupy? | `syncr_solver.inputs` |
| `anchors` | what is externally committed and unmovable? | `syncr_api.anchors` |
| `absolute_forbidden` | what is unavailable to EVERY Area? | `syncr_domain.discretionary` |
| `scoped_forbidden` | what is unavailable to SOME Areas? | `syncr_domain.gaps` |
| `off_plan` | what did the user declare off-plan? | `syncr_domain.off_plan` |
| `placed` | what capacity is already committed? | `syncr_solver.inputs` |
| `area_floor_reservations` | what must be reserved per Area? | `syncr_api.plans.reservations` |
| `area_targets` | what is each Area aiming at? no check reads it | `syncr_domain.budgets` |
| `deadline_demands` | what work must fit before when? | `syncr_api.plans.demand` |

The questions are short because the answers are not. ``span`` is the whole week and ``now`` is
where capacity starts; ``frame`` is this week's occurrences together with the ones it inherited,
at effective durations; ``absolute_forbidden`` is recovery scoped to every Area plus the buffers
no Area claims; ``scoped_forbidden`` is capacity for every Area a window does not name; ``placed``
is every live-plan block and every pin, past and future. The three netted quantities are stated
below.

## Two fields that look like one quantity, and are not

``now`` and ``computed_at`` carry one value in every projection the assembler produces, and they
answer different questions. The arithmetic reads ``now`` and never ``computed_at``; the verdict
carries ``computed_at`` and never ``now``. Nothing compares them: an assembly reproducing a past
failure is stamped at the instant it is reproducing, and a verdict computed from it is a fact
about that instant rather than about the wall clock.

``span`` and ``now`` are the pair that took three reviews to separate. The denominator is taken
over the whole week so the budget report's figure is stable as the week elapses; capacity starts
at ``now``, because roughly a third of a week's discretionary time sits in no block and crediting
the user with hours that have already gone is how skipping work came to improve the verdict.

## Netted quantities arrive net

``area_floor_reservations`` and ``deadline_demands`` are both already net of committed capacity,
and both net **every** placement, pinned or not, past or future. That is the same set the probe's
free capacity subtracts, which is what keeps both sides of every comparison counting one set. The
solver's own floor and remaining-work figures net a narrower set for a reason that is the
solver's, and neither of those reaches this struct.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from syncr_domain.feasibility.errors import FeasibilityError
from syncr_domain.intervals import IntervalSet, as_instant

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_domain.identifiers import AreaId
    from syncr_domain.intervals import Instant, Interval


@dataclass(frozen=True, slots=True, kw_only=True)
class ScopedWindow:
    """A forbidden window that names the Areas it forbids, and is capacity for every other one.

    Recovery the user scoped to named Areas. It cannot be subtracted from a whole-week figure
    without manufacturing a shortfall that does not exist: a week with two typed interviews
    reserves a couple of hours that Fitness, Admin, and Research could each have used.
    """

    interval: Interval
    forbidden_area_ids: tuple[AreaId, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "forbidden_area_ids", tuple(self.forbidden_area_ids))
        if not self.forbidden_area_ids:
            raise FeasibilityError(
                "a scoped window names the Areas it forbids, and this one names none: a window "
                "forbidding nobody is not scoped, and a window forbidding everybody is absolute"
            )

    def forbids(self, area_id: AreaId) -> bool:
        """Whether this window is unavailable to that Area."""
        return area_id in self.forbidden_area_ids


@dataclass(frozen=True, slots=True, kw_only=True)
class FloorReservation:
    """How much of one Area's floor is still to be found, and what the Area is called.

    ``reserved_minutes`` is the declared floor less the minutes placed in that Area by ANY
    block, pinned or not, past or future, clamped at zero. An over-satisfied floor reserves
    nothing, and a floor already met by unpinned solver-placed blocks reserves nothing either:
    that is the normal healthy state of a solved week, and reserving against it reported a gap
    on every week the product had already planned.

    ``label`` is the Area's own name, carried because a shortfall names what cannot be satisfied
    in the user's words. Resolving an identifier is a lookup, and this package performs none.
    """

    area_id: AreaId
    reserved_minutes: int
    label: str

    def __post_init__(self) -> None:
        if self.reserved_minutes < 0:
            raise FeasibilityError(
                f"a reservation of {self.reserved_minutes} minutes is not a duration: a floor "
                "met by more than it asked for reserves nothing, which is zero"
            )
        if not self.label.strip():
            raise FeasibilityError(
                "a floor reservation carries the Area's name, because a shortfall names what "
                "cannot be satisfied in the user's words, and an unnamed Area names nothing"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class DeadlineDemand:
    """How much work one Area owes before one instant, and which tasks make it up.

    ``remaining_minutes`` is net, deadline-scoped, and ``max()``-corrected: per task it is the
    corrected estimate less ``max(recorded, minutes placed in the past before the deadline)``
    less minutes placed in the future before the deadline. EVERY placement counts, pinned or
    not, because the probe's free capacity subtracts every placement.

    **This is the probe's demand.** The solver reads its own remaining-work figure, which nets a
    narrower set. Several tasks sharing one deadline in one Area are one demand, because they
    compete for the same capacity and two demands would each be checked against the whole of it.
    """

    deadline: Instant
    remaining_minutes: int
    area_id: AreaId
    labels: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "deadline", as_instant(self.deadline))
        object.__setattr__(self, "labels", tuple(self.labels))
        if self.remaining_minutes < 0:
            raise FeasibilityError(
                f"a demand for {self.remaining_minutes} minutes is not work outstanding: a task "
                "whose placements already cover its estimate demands nothing, which is zero"
            )
        if not self.labels or not all(label.strip() for label in self.labels):
            raise FeasibilityError(
                f"a demand names the tasks that make it up, and this one names {list(self.labels)}"
                ": the shortfall it produces says what cannot be finished, by name"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class ProbeInputs:
    """One week's capacity arithmetic, resolved. The probe performs no lookup over this.

    A frozen dataclass with a default for every collection, deliberately: the arithmetic is
    property-tested from literals, and needing an assembly to state a case is how arithmetic
    goes untested. Every field is documented in the table above.
    """

    span: Interval
    now: Instant
    computed_at: Instant
    input_version: int

    frame: IntervalSet = field(default_factory=IntervalSet)
    anchors: IntervalSet = field(default_factory=IntervalSet)
    absolute_forbidden: IntervalSet = field(default_factory=IntervalSet)
    scoped_forbidden: tuple[ScopedWindow, ...] = ()
    off_plan: IntervalSet = field(default_factory=IntervalSet)
    placed: IntervalSet = field(default_factory=IntervalSet)
    area_floor_reservations: tuple[FloorReservation, ...] = ()
    area_targets: Mapping[AreaId, int] = field(default_factory=dict)
    deadline_demands: tuple[DeadlineDemand, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "now", as_instant(self.now))
        object.__setattr__(self, "computed_at", as_instant(self.computed_at))
        object.__setattr__(self, "area_targets", dict(self.area_targets))
        object.__setattr__(self, "scoped_forbidden", tuple(self.scoped_forbidden))
        object.__setattr__(self, "area_floor_reservations", tuple(self.area_floor_reservations))
        object.__setattr__(self, "deadline_demands", tuple(self.deadline_demands))

    def scoped_against(self, area_id: AreaId) -> IntervalSet:
        """The windows this Area may not use, as one set.

        The one reading of the scope. A caller asking "what may this Area claim" subtracts this
        from free capacity; a whole-week figure subtracts none of it, because every window here
        is capacity for the Areas it does not name.
        """
        return IntervalSet(
            window.interval for window in self.scoped_forbidden if window.forbids(area_id)
        )
