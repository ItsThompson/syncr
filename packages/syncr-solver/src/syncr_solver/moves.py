"""The four move kinds a local search may take, each as a candidate plan the objective judges.

```
relocate   one block to another legal window
swap       two blocks' intervals
resize     an elastic occurrence to another length in its range
re-split   a divisible task's pieces into a different division
```

Four rather than one because each reaches a plan the others cannot. Relocating cannot exchange two
blocks whose windows each hold only the other; resizing cannot move; and re-splitting changes how
many blocks a task has, which no move over existing blocks can.

## Only what this solve chose is moved

The frame, the imported commitments, the buffers, the concrete entries, the blocks that have begun,
and the pins are the space rather than candidates inside it, so no move touches one. Offered
anyway, every such move would be refused by H10 or H11 on every window, and the search would spend
its whole budget proving that.

## A move is proposed rather than applied

Each generator answers with the attempt the move WOULD produce, or with nothing because the rules
refused it. The search then evaluates the objective and keeps it only on a strict improvement, so a
move that makes the plan worse is arithmetic that happened rather than a state to undo.

## Why a move rebuilds the state rather than editing it

A candidate has to be judged against a week that no longer holds the block being moved: checked
against the state that still holds it, H4 would refuse every relocation for overlapping itself. So a
move builds the attempt without the placements it is changing, offers the new ones into that, and
carries the accepted result forward. The rebuild is what makes the removal expressible at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.identity import BindingKind
from syncr_solver.attempt import Attempt
from syncr_solver.candidates import candidates_for
from syncr_solver.offering import offer_at, offers_in, refusal_of, windows_for
from syncr_solver.reading import demand_key

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from syncr_domain.intervals import Interval
    from syncr_solver.attempt import Placed
    from syncr_solver.candidates import Candidate
    from syncr_solver.preferred import ResolvedPreferences
    from syncr_solver.reading import DemandKey


@dataclass(frozen=True, slots=True, kw_only=True)
class Move:
    """One proposed change: what kind it is, and the plan it would produce."""

    kind: str
    attempt: Attempt


RELOCATE = "relocate"
SWAP = "swap"
RESIZE = "resize"
RESPLIT = "re_split"


def moves(attempt: Attempt, preferences: ResolvedPreferences) -> Iterator[Move]:
    """Every move this plan offers, in one deterministic order.

    The kinds run in the order the design lists them and each runs over the chosen placements in
    span order, so two searches over one plan consider the same moves in the same sequence. That is
    what makes "the same input always consumes the same number of iterations" a property of the
    generator rather than a hope about the loop.
    """
    chosen = _chosen(attempt)
    yield from _relocations(attempt, chosen, preferences)
    yield from _swaps(attempt, chosen)
    yield from _resizes(attempt, chosen)
    yield from _resplits(attempt, chosen, preferences)


def _chosen(attempt: Attempt) -> tuple[Placed, ...]:
    """The placements this solve chose, in span order, so a move set has one order."""
    return tuple(
        sorted(
            (held for held in attempt.placements if held.chosen),
            key=lambda held: (held.block.interval.start, held.block.interval.end, held.block.id),
        )
    )


def _relocations(
    attempt: Attempt, chosen: Sequence[Placed], preferences: ResolvedPreferences
) -> Iterator[Move]:
    """Each chosen block offered into every other legal window of the week it leaves behind."""
    for held in chosen:
        rest = _without(attempt, (held,))
        candidate = _candidate_of(held, rest)
        if candidate is None:
            continue
        for window in windows_for(candidate, rest.gaps(), preferences):
            for offer in offers_in(candidate, window, attempt=rest):
                if offer.interval == held.block.interval:
                    continue
                if refusal_of(offer, rest) is None:
                    yield Move(kind=RELOCATE, attempt=rest.adding(offer.placed))
                    break


def _swaps(attempt: Attempt, chosen: Sequence[Placed]) -> Iterator[Move]:
    """Every pair of chosen blocks, each offered at the other's interval.

    Only pairs of equal length: two blocks of different lengths exchanged would each need its
    neighbour's slack as well, which is a relocation of both and not a swap. Restricting the move
    keeps it decidable from the pair alone.
    """
    for first in range(len(chosen)):
        for second in range(first + 1, len(chosen)):
            left, right = chosen[first], chosen[second]
            if left.block.interval.total_minutes() != right.block.interval.total_minutes():
                continue
            rest = _without(attempt, (left, right))
            moved = _exchanged(left, right, rest)
            if moved is not None:
                yield Move(kind=SWAP, attempt=moved)


def _exchanged(left: Placed, right: Placed, rest: Attempt) -> Attempt | None:
    """The plan holding each of these two blocks at the other's interval, or nothing."""
    first = _candidate_of(left, rest)
    second = _candidate_of(right, rest)
    if first is None or second is None:
        return None
    one = offer_at(first, right.block.interval, attempt=rest)
    if refusal_of(one, rest) is not None:
        return None
    with_one = rest.adding(one.placed)
    other = offer_at(second, left.block.interval, attempt=with_one)
    if refusal_of(other, with_one) is not None:
        return None
    return with_one.adding(other.placed)


def _resizes(attempt: Attempt, chosen: Sequence[Placed]) -> Iterator[Move]:
    """Each elastic occurrence at every other length its range allows, in the window it holds.

    The window is the gap the block's own start falls in once the block is out of the way, so a
    resize is a length change rather than a move: the relocate kind is what changes a start.
    """
    for held in chosen:
        if held.block.binding.kind is not BindingKind.HABIT:
            continue
        rest = _without(attempt, (held,))
        candidate = _candidate_of(held, rest)
        if candidate is None or candidate.min_minutes == candidate.max_minutes:
            continue
        for window in _around(held, rest):
            for offer in offers_in(candidate, window, attempt=rest):
                if offer.interval == held.block.interval:
                    continue
                if refusal_of(offer, rest) is None:
                    yield Move(kind=RESIZE, attempt=rest.adding(offer.placed))


def _resplits(
    attempt: Attempt, chosen: Sequence[Placed], preferences: ResolvedPreferences
) -> Iterator[Move]:
    """Each divided task's pieces dropped and re-placed, so the division itself can change.

    Dropping every piece and letting the packer choose again is what makes the number of pieces a
    thing the search can change: a move over one piece can only ever move that piece.
    """
    for key in _divided(chosen):
        pieces = tuple(held for held in chosen if demand_key(held.block.binding) == key)
        rest = _without(attempt, pieces)
        candidate = _candidate_of(pieces[0], rest)
        if candidate is None:
            continue
        rebuilt = _repacked(candidate, rest, preferences)
        if rebuilt is not None:
            yield Move(kind=RESPLIT, attempt=rebuilt)


def _repacked(
    candidate: Candidate, rest: Attempt, preferences: ResolvedPreferences
) -> Attempt | None:
    """This task's whole remaining work placed again, greedily, into the week without it.

    The pieces are taken from the earliest legal window each time, which is a different division
    from the one construction produced whenever the freed time changed what fits. Nothing is scored
    here: the search scores the whole result once, which is what keeps a move one evaluation.
    """
    rebuilt = rest
    placed = False
    while True:
        current = _candidate_of_binding(candidate, rebuilt)
        if current is None:
            return rebuilt if placed else None
        offer = next(
            (
                found
                for window in windows_for(current, rebuilt.gaps(), preferences)
                for found in offers_in(current, window, attempt=rebuilt)
                if refusal_of(found, rebuilt) is None
            ),
            None,
        )
        if offer is None:
            return rebuilt if placed else None
        rebuilt = rebuilt.adding(offer.placed)
        placed = True


def _divided(chosen: Sequence[Placed]) -> tuple[DemandKey, ...]:
    """The tasks this plan holds pieces of, in the order their first piece was placed."""
    found: list[DemandKey] = []
    for held in chosen:
        if held.block.binding.kind is not BindingKind.TASK:
            continue
        key = demand_key(held.block.binding)
        if key not in found:
            found.append(key)
    return tuple(found)


def _without(attempt: Attempt, dropped: Sequence[Placed]) -> Attempt:
    """This plan without those placements, with the state rebuilt so the spans are free again."""
    return Attempt.of(
        attempt.inputs,
        placements=[
            held for held in attempt.placements if not any(held is gone for gone in dropped)
        ],
        slots=attempt.slots,
        log=attempt.log,
    )


def _around(held: Placed, rest: Attempt) -> tuple[Interval, ...]:
    """The gap this block's start falls in, once the block itself is out of the way."""
    return tuple(gap for gap in rest.gaps() if gap.start <= held.block.interval.start < gap.end)


def _candidate_of(held: Placed, rest: Attempt) -> Candidate | None:
    """The candidate this block was placed from, rebuilt against the week without it.

    Rebuilt rather than stored, because what a candidate says about a demand changes as the week
    changes: a task's remaining minutes and an Area's unmet floor are both facts about the plan the
    candidate is being offered into.
    """
    wanted = demand_key(held.block.binding)
    return next(
        (
            candidate
            for candidate in candidates_for(
                rest.inputs,
                placed_minutes=rest.placed_minutes(),
                held_demands=rest.held_demands(),
                floor_shortfalls=rest.floor_shortfalls(),
            )
            if demand_key(candidate.binding) == wanted
        ),
        None,
    )


def _candidate_of_binding(candidate: Candidate, rebuilt: Attempt) -> Candidate | None:
    """This candidate as the plan now sees it, or nothing because it has nothing left to place."""
    wanted = demand_key(candidate.binding)
    return next(
        (
            found
            for found in candidates_for(
                rebuilt.inputs,
                placed_minutes=rebuilt.placed_minutes(),
                held_demands=rebuilt.held_demands(),
                floor_shortfalls=rebuilt.floor_shortfalls(),
            )
            if demand_key(found.binding) == wanted
        ),
        None,
    )
