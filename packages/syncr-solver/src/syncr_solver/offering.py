"""Turning one candidate and one window into a block the checker can judge, and scoring it.

Construction and local search both need the same three steps: build the placement a candidate
would take in a window, ask the thirteen rules about it, and score the plan it would produce. All
three are here, so the two phases cannot come to build a block two different ways.

## Which windows a candidate is offered in, and why the order is not the span order alone

Every gap is offered, and the gaps whose span meets one of the candidate's own preferred windows
are offered first. The objective is still what decides -- ``time_of_day_misfit`` is what prices a
window, and this chooses nothing -- but a solve may only score a bounded number of windows per
candidate, so the order decides which windows get scored at all. Ordered by span alone, a preferred
Saturday morning would never be reached on a week whose Monday has room.

## One offer per length, at the earliest start the window allows

A candidate's length comes from :mod:`syncr_solver.elastic`, and its start is the first point of
the grid the window holds. Trying every start inside a window is the relocate move's job, and doing
it here would multiply the objective evaluations a construction spends by the number of grid steps
in a week.

## A piece too short to be legal is offered anyway

A task whose remaining work is longer than every gap is offered the largest piece a gap can hold,
even when that is below the minimum chunk its content declares. H6 or H7 then refuses it and the
refusal reaches the log with its rule and its window, which is what makes a packing failure
something the verdict can name rather than an absence nobody recorded.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from syncr_domain.identity import BindingKind, BindingRef
from syncr_domain.intervals import Interval
from syncr_domain.plan import Block
from syncr_domain.reasons import ReasonRecord
from syncr_domain.snap import SNAP, SNAP_MINUTES, is_on_snap_grid, snap_to_grid
from syncr_solver.attempt import Placed, chunk_ordinal
from syncr_solver.constraints import BlockedCandidate, ConstraintCheck
from syncr_solver.elastic import sizes_for
from syncr_solver.objective import evaluate
from syncr_solver.rules import HARD_RULES

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from syncr_domain.intervals import Instant
    from syncr_solver.attempt import Attempt
    from syncr_solver.candidates import Candidate
    from syncr_solver.objective import ObjectiveBreakdown
    from syncr_solver.preferred import ResolvedPreferences
    from syncr_solver.weights import WeightSet

# The rules every offer is judged against. A value at the call site rather than a default inside
# the checker, which is what lets a derivation check the occupancy subset and a solve check all
# thirteen without either being a mode.
CHECK: Final = ConstraintCheck(HARD_RULES)


@dataclass(frozen=True, slots=True, kw_only=True)
class Offer:
    """One placement of one candidate, as the block it becomes and the placement rules judge."""

    candidate: Candidate
    placed: Placed

    @property
    def interval(self) -> Interval:
        return self.placed.block.interval


@dataclass(frozen=True, slots=True, kw_only=True)
class Scored:
    """One accepted offer, and what the plan holding it costs."""

    offer: Offer
    breakdown: ObjectiveBreakdown
    total: float


def offers_in(candidate: Candidate, window: Interval, *, attempt: Attempt) -> Iterator[Offer]:
    """Every placement of this candidate the window could hold, longest first.

    The window is a gap or a slot's declared span. A length longer than the window holds is not
    offered, except for the one case the module docstring states: a task is offered the largest
    piece the window can hold, so a piece below its minimum chunk reaches the rule that names it.
    """
    start = _first_grid_point_at_or_after(window.start)
    room = _minutes_between(start, window.end)
    if room < SNAP_MINUTES:
        return
    for minutes in sizes_for(candidate, attempt):
        length = min(minutes, room) if _packs_to_the_window(candidate) else minutes
        if length < SNAP_MINUTES or length > room:
            continue
        yield offer_at(
            candidate, Interval(start, start + timedelta(minutes=length)), attempt=attempt
        )


def offer_at(candidate: Candidate, interval: Interval, *, attempt: Attempt) -> Offer:
    """The placement this candidate takes at exactly this interval.

    The block carries the ``bound`` clause the candidate resolved, so a placed block satisfies the
    one-clause minimum from the moment it exists rather than once a reason record is assembled.
    """
    binding, count = _chunking(candidate, attempt)
    block = Block(
        iso_week=attempt.inputs.iso_week,
        interval=interval,
        binding=binding,
        title=candidate.title,
        reason=ReasonRecord((candidate.bound,)),
        area_id=candidate.area_id,
        split_count=count,
    )
    return Offer(candidate=candidate, placed=Placed.of(block, sizing=candidate.sizing, chosen=True))


def refusal_of(offer: Offer, attempt: Attempt) -> BlockedCandidate | None:
    """The first rule this offer breaks against the week as it stands, or nothing."""
    rejection = CHECK.check(offer.placed.placement, attempt.state)
    if rejection is None:
        return None
    return BlockedCandidate.of(offer.candidate.binding, rejection)


def scored(offer: Offer, attempt: Attempt, weights: WeightSet) -> Scored:
    """What the week costs with this offer placed in it.

    The whole plan rather than the block, because every one of the seven terms is a fraction of
    something the week holds: a block's own cost is not a quantity the objective has.
    """
    breakdown = evaluate(
        attempt.adding(offer.placed).document(), inputs=attempt.inputs, weights=weights
    )
    return Scored(offer=offer, breakdown=breakdown, total=breakdown.total())


def windows_for(
    candidate: Candidate, gaps: Sequence[Interval], preferences: ResolvedPreferences
) -> tuple[Interval, ...]:
    """These gaps in the order this candidate is offered them: the preferred ones first.

    Stable inside each half, so the whole order is a function of the gaps and the candidate. The
    strengths are not separated: a preference carries one strength and an override replaces its
    Area's declaration wholly, so a candidate has strong windows or soft ones and never both.
    """
    preferred = tuple(
        window
        for preference in preferences.applying_to(candidate.binding, candidate.area_id)
        for window in preference.windows
    )
    if not preferred:
        return tuple(gaps)
    meets = [gap for gap in gaps if any(gap.overlaps(window) for window in preferred)]
    rest = [gap for gap in gaps if not any(gap.overlaps(window) for window in preferred)]
    return (*meets, *rest)


def _packs_to_the_window(candidate: Candidate) -> bool:
    """Whether a length longer than the window becomes the largest piece the window can hold.

    True for a task, whose remaining work is divided into what fits. False for an occurrence, whose
    length is a declaration about one session: shortening it below the range would place a session
    the habit says is not one.
    """
    return candidate.binding.kind is BindingKind.TASK


def _chunking(candidate: Candidate, attempt: Attempt) -> tuple[BindingRef, int | None]:
    """The identity this placement carries, and how many chunks it claims to be one of.

    A divisible task's pieces are numbered as they are placed, and the FIRST piece carries no number
    at all: most tasks are placed whole, one chunk is the whole task, and the domain spells that by
    carrying neither a number nor a count. A second piece therefore starts at one and the document
    build gives the first piece number zero once it knows a second exists.

    An atomic task carries no number either, and for a different reason: H6 reads one as a division
    of something that has none, and an atomic demand is placed whole or not at all.
    """
    if candidate.binding.kind is not BindingKind.TASK or not candidate.sizing.splittable:
        return (candidate.binding, None)
    ordinal = chunk_ordinal(attempt.placements, candidate.binding)
    if ordinal == 0:
        return (candidate.binding, None)
    return (
        BindingRef.for_task(candidate.binding.entity_id, split_index=ordinal),
        ordinal + 1,
    )


def _first_grid_point_at_or_after(moment: Instant) -> Instant:
    """The first fifteen-minute point at or after ``moment``.

    A gap can open off the grid, because an imported commitment keeps its real time and the buffers
    derived from it are computed from that time. H14 binds everything the solver places, so the
    start is moved forward rather than rounded: rounding back would start a block inside the
    commitment the gap opens after.
    """
    if is_on_snap_grid(moment):
        return moment
    snapped = snap_to_grid(moment)
    return snapped if snapped > moment else snapped + SNAP


def _minutes_between(start: Instant, end: Instant) -> int:
    """Whole grid steps' worth of minutes from ``start`` to ``end``, and zero when it runs back."""
    if end <= start:
        return 0
    minutes = int((end - start).total_seconds() // 60)
    return minutes - minutes % SNAP_MINUTES
