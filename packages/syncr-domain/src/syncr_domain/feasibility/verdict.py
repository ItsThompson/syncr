"""What a feasibility check answers with: a verdict, its provenance, and its shortfalls.

**Four shortfall kinds, and this module is their only home.** The vocabulary crosses the API
boundary, renders in the verdict panel and the CLI, and is aggregated by the product-metric job,
so a second spelling of it anywhere would be a second vocabulary. Three of the four are produced
by :func:`syncr_domain.feasibility.probe.probe`; the fourth is the packing failure capacity
arithmetic structurally cannot find, and :func:`minimum_chunk_shortfall` is where it is built so
the solver's verdict assembly emits a named member rather than inventing one.

**A probe verdict may never claim a week is feasible.** Capacity arithmetic can prove
infeasibility and cannot prove feasibility: a week whose capacity is sufficient can still fail
to pack, because the capacity exists in the wrong shape. So ``feasible`` is refused at
construction for a ``probe`` verdict, and the reading a caller wants for "we found nothing
wrong" is :attr:`Verdict.capacity_is_sufficient`.

**A shortfall names four things and one of them is what makes it actionable.** The minutes, what
cannot be satisfied, the deadline where one applies, and ``honoring``: the constraints being
respected that produced the gap. A refusal that names no honored constraint tells the user their
week is impossible without telling them which of their own decisions made it so, which is the
half that lets them choose a tradeoff. It is refused at construction for that reason.

Durations in ``against`` and ``honoring`` are rendered here because the phrase is the product's
own wording and one wording is the point. **Instants are not**, in either field: rendering
``Fri 09:00`` needs the zone the user is in that day, which this package deliberately cannot
reach. A surface renders ``deadline`` itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from syncr_domain.budgets import MINUTES_PER_HOUR
from syncr_domain.feasibility.errors import FeasibilityError
from syncr_domain.intervals import as_instant

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from syncr_domain.identifiers import AreaId
    from syncr_domain.intervals import Instant
    from syncr_domain.plan import AdjustmentKind


class Provenance(StrEnum):
    """Which kind of check produced a verdict, and therefore which claim it may make.

    ``probe`` may say "this week is infeasible, by this much, against this commitment", and at
    most that capacity is sufficient. ``solver`` may say either, because it attempted a
    placement and knows the answer.
    """

    PROBE = "probe"
    SOLVER = "solver"


class ShortfallKind(StrEnum):
    """Why a week cannot hold its commitments. Four kinds, and no fifth spelling anywhere.

    The first three are capacity arithmetic and the probe produces all three. The fourth is a
    packing failure: the capacity exists but not in a usable shape, which no arithmetic over
    interval totals can discover and only an attempted placement can.
    """

    # Every Area floor together needs more time than the week has left.
    FLOORS_EXCEED_CAPACITY = "floors_exceed_capacity"
    # The work due before one deadline needs more time than that Area has before it.
    DEADLINE_CAPACITY = "deadline_capacity"
    # One Area cannot reach its own floor in the time it is allowed to claim.
    AREA_FLOOR_UNREACHABLE = "area_floor_unreachable"
    # The remaining time is there and no single piece of it is long enough to use: a task
    # needing a 50-minute chunk against six 30-minute gaps between lectures.
    MINIMUM_CHUNK_UNPLACEABLE = "minimum_chunk_unplaceable"


def hours_and_minutes(minutes: int) -> str:
    """A duration as the verdict panel, the CLI, and a tradeoff label print it.

    ``5h``, ``1h20m``, ``45m``, ``0m``. One rendering, because the same duration appears in a
    shortfall's honored constraint and in the label of the tradeoff offered against it, and two
    renderings of one figure is how the panel comes to disagree with itself.
    """
    if minutes < 0:
        raise FeasibilityError(f"{minutes} minutes is not a duration, so it renders as nothing")
    hours, remainder = divmod(minutes, MINUTES_PER_HOUR)
    if hours and remainder:
        return f"{hours}h{remainder}m"
    if hours:
        return f"{hours}h"
    return f"{remainder}m"


@dataclass(frozen=True, slots=True, kw_only=True)
class Shortfall:
    """One quantified gap: how much, against what, by when, and what was honored to get there.

    ``minutes`` is the gap rather than the demand, so it is what a tradeoff has to recover.
    ``against`` names what cannot be satisfied and ``honoring`` names the constraints that were
    respected while computing it. ``deadline`` is present only for a gap measured against one,
    and ``area_id`` only for a gap that belongs to one Area.

    | Field | The question it answers |
    |---|---|
    | `kind` | which check produced this gap? |
    | `minutes` | how much cannot fit? what a tradeoff must recover |
    | `against` | what cannot be satisfied, by name? |
    | `honoring` | which of the user's own constraints took the capacity? |
    | `deadline` | against what instant was this measured, where one applies? |
    | `area_id` | whose gap is this, where it belongs to one Area? |
    | `honored_floor_minutes` | what did each honored floor take? no check reads it |
    The last row is reporting only, like a target on the probe's inputs: it exists so a stated
    recovery can be exact, and no check reads it.
    """

    kind: ShortfallKind
    minutes: int
    against: tuple[str, ...]
    honoring: tuple[str, ...]
    deadline: Instant | None = None
    area_id: AreaId | None = None
    # Per honored floor, ``(label, minutes)``: the part of that floor the check read as competing
    # inside the window, which the honoring phrase does not state because it names the floor at its
    # DECLARED size. Carried so a stated recovery can be exact; no check reads it, so a producer
    # that states none states nothing a refusal depends on.
    honored_floor_minutes: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "against", tuple(self.against))
        object.__setattr__(self, "honoring", tuple(self.honoring))
        object.__setattr__(self, "honored_floor_minutes", tuple(self.honored_floor_minutes))
        if self.deadline is not None:
            object.__setattr__(self, "deadline", as_instant(self.deadline))
        if self.minutes <= 0:
            raise FeasibilityError(
                f"a shortfall of {self.minutes} minutes is not a gap: a check that found "
                "enough capacity reports nothing rather than a gap of none"
            )
        _require_a_name(self.against, "against", "what cannot be satisfied")
        _require_a_name(self.honoring, "honoring", "the constraints that produced the gap")


@dataclass(frozen=True, slots=True, kw_only=True)
class Tradeoff:
    """One concession the user could approve to close a shortfall, and what it recovers.

    The four kinds are ``AdjustmentKind``: a tradeoff the user approves becomes the concession
    of the same kind, so the two are one vocabulary rather than one spelled twice.

    ``label`` is rendered text because the wording is per kind and per target ("Reduce sleep by
    20m on Tue, Wed and Thu" names the nights, because the concession stores them).

    ``delta_minutes`` is what a concession would recover, in minutes, and it is an **upper bound**
    on the movement it produces rather than an exact figure: the component that enumerates these
    states the three cases where it can promise more than approving it delivers. Never less, which
    is the direction a panel can safely be wrong in.

    **Nothing in this package builds one, and a probe verdict carries none.** Enumeration needs the
    identity of the task, routine, or Area a concession would act on, and capacity arithmetic reads
    no identifier: the caller that renders a verdict enumerates over the same assembly the probe
    read, and hands the result back on the verdict.
    """

    kind: AdjustmentKind
    label: str
    target_id: UUID
    delta_minutes: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Verdict:
    """Whether a week can hold its commitments, how that was decided, and by how much it cannot.

    ``computed_at`` and ``input_version`` are both stamped from the inputs rather than read
    here: a verdict is a fact about one assembly, so two computations over one assembly are
    equal and a recorded transition names the version it was computed against.
    """

    feasible: bool
    provenance: Provenance
    computed_at: Instant
    input_version: int
    # The week's denominator, over the WHOLE span rather than the capacity left in it, so the
    # figure the verdict was computed against is the one the budget report renders. Carried so
    # neither surface re-derives it from a second subtraction.
    discretionary_minutes: int
    shortfalls: tuple[Shortfall, ...] = ()
    # Empty from the probe, which reads no identifier and so cannot name what a concession would
    # act on. The caller that renders a verdict enumerates one per gap over the same assembly.
    tradeoffs: tuple[Tradeoff, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "computed_at", as_instant(self.computed_at))
        object.__setattr__(self, "shortfalls", tuple(self.shortfalls))
        object.__setattr__(self, "tradeoffs", tuple(self.tradeoffs))
        if self.discretionary_minutes < 0:
            raise FeasibilityError(
                f"a week holding {self.discretionary_minutes} discretionary minutes holds no "
                "week: the denominator is a subtraction from a span, so it cannot go below zero"
            )
        _require_no_feasibility_claimed_from_arithmetic(self.feasible, self.provenance)

    @property
    def capacity_is_sufficient(self) -> bool:
        """Whether this check found no gap. **Not** a claim that the week works.

        The reading a panel wants from a probe verdict, and the one it must render instead of
        ``feasible``: capacity arithmetic finding nothing means it could not prove the week
        impossible, which is a weaker statement than the week being possible.
        """
        return not self.shortfalls


def minimum_chunk_shortfall(
    *,
    minutes: int,
    chunk_minutes: int,
    against: Sequence[str],
    blocked_by: Sequence[str] = (),
    deadline: Instant | None = None,
    area_id: AreaId | None = None,
) -> Shortfall:
    """The gap for work whose smallest usable piece no remaining window can hold.

    The one producer of ``MINIMUM_CHUNK_UNPLACEABLE``, and the only kind capacity arithmetic
    cannot reach: three hours of free time in six half-hour gaps is three hours by every total
    the probe takes and no minutes at all to a task that cannot be split below fifty.

    ``blocked_by`` is what rejected each candidate window, which the solver holds per attempt.
    The minimum chunk is named first because it is the constraint the user can act on: it is
    their own declaration about how small a session may usefully be.
    """
    return Shortfall(
        kind=ShortfallKind.MINIMUM_CHUNK_UNPLACEABLE,
        minutes=minutes,
        against=tuple(against),
        honoring=(f"its {hours_and_minutes(chunk_minutes)} minimum chunk", *blocked_by),
        deadline=deadline,
        area_id=area_id,
    )


def _require_a_name(named: tuple[str, ...], stated: str, what: str) -> None:
    """A rendered list with no readable member renders as nothing, so it is refused.

    Both fields are what a refusal is made of: one says what the user cannot have and the other
    says which of their own constraints took it. An empty member is worse than an absent field,
    because a panel renders the separators around it.
    """
    if not named or not all(member.strip() for member in named):
        raise FeasibilityError(
            f"a shortfall's {stated!r} names {what}, and this one names {list(named)}: a gap "
            "the user cannot read is a gap they cannot choose a tradeoff against"
        )


def _require_no_feasibility_claimed_from_arithmetic(feasible: bool, provenance: Provenance) -> None:
    """The one claim the product must never make, refused where the claim is constructed.

    A week can pass every capacity total and still not pack, so no arithmetic verdict is
    evidence that a week works. Refused at construction rather than left to each surface,
    because five of them read this field.
    """
    if feasible and provenance is Provenance.PROBE:
        raise FeasibilityError(
            "capacity arithmetic cannot prove a week feasible: it proves the opposite, or it "
            "reports that capacity is sufficient. Read `capacity_is_sufficient` instead"
        )
