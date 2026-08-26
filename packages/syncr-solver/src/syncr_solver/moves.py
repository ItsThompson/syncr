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

## Why the four generators share one file, over the 300-line guidance

This module is above it. Every one of the four reads ``_without``, and three of them read
``_moved_to`` or ``_candidate_of`` as well, so splitting by kind would put four callers of three
helpers in five files and the reader would follow a move across two of them to see what it does. The
chunk numbering that used to live in :mod:`syncr_solver.attempt` was the opposite case and was
lifted: it had its own question and no shared machinery. Revisit this if a fifth kind arrives.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from syncr_domain.identity import BindingKind
from syncr_domain.intervals import Interval
from syncr_solver.attempt import Attempt, Placed
from syncr_solver.candidates import candidates_for
from syncr_solver.offering import (
    CHECK,
    offers_in,
    preferred_first,
    refusal_of,
    starts_in,
    windows_for,
)
from syncr_solver.ordering import block_key
from syncr_solver.reading import demand_key

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from syncr_domain.intervals import Instant
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
    yield from _resizes(attempt, chosen, preferences)
    yield from _resplits(attempt, chosen, preferences)


def _chosen(attempt: Attempt) -> tuple[Placed, ...]:
    """The placements this solve chose, in span order, so a move set has one order.

    **The filter is an optimization for three of the four kinds and it is the RULE for the fourth.**
    Relocate, swap and resize move a placement under its own binding, so H11 matches the binding
    the week already holds and refuses the move: offering one produces no move and spends the
    budget proving it. **Re-split is different.** It drops every piece of a divided task and lets
    the packer place the work again; a re-placed piece takes a NEW chunk number, so its binding is
    not the one ``state.immovable`` holds and H11 has nothing to refuse. A re-split that dropped a
    pinned piece would therefore be accepted whenever it priced better, and the pin would be gone
    from the proposal with no rule having spoken.

    Measured on a week whose pinned chunk is netted out of the demand, so re-placing the work does
    not put it back, and whose Area target makes losing two hours an improvement: the objective
    falls from 4.667 to 1.667, the search accepts, and the pin is lost.

    So the filter is applied at three points rather than one, each of which independently prevents
    the loss: here, in :func:`_divided`, and in the pieces :func:`_resplits` drops. Any one of them
    suffices, which is why no single bite reddens and the bite of all three reddens 2. That is
    defence in depth over a property no rule can enforce, not three statements of one rule.
    """
    return tuple(
        sorted(
            (held for held in attempt.placements if held.chosen),
            key=lambda held: block_key(held.block),
        )
    )


def _relocations(
    attempt: Attempt, chosen: Sequence[Placed], preferences: ResolvedPreferences
) -> Iterator[Move]:
    """Each chosen block offered at one start of every other gap of the week it leaves behind.

    A relocation moves a block and keeps it: the content and the length are unchanged, so nothing
    here rebuilds a candidate. Re-deriving one would ask the week what a demand still owes, which is
    a question a relocation does not change the answer to, and it cost 1.2 s of a 2.5 s solve.

    The start is ONE per block per pass, which is the size the move budget was measured against.
    Each roomy gap is read through :func:`starts_in`, which puts the starts of the block's OWN
    windows inside the gap ahead of the gap's opening -- so the first relocation found is the one
    INTO its window when one exists, and a declared window strictly inside a roomy gap gets
    reached rather than only wherever the gap happens to open. Either way the pass holds one
    relocation candidate per block, and the descent spends the move budget on exactly as many of
    them as it did before.
    """
    for held in chosen:
        rest = _without(attempt, (held,))
        moved = _first_legal_relocation(held, rest, preferences)
        if moved is not None:
            yield Move(kind=RELOCATE, attempt=rest.adding(moved))


def _first_legal_relocation(
    held: Placed,
    rest: Attempt,
    preferences: ResolvedPreferences,
) -> Placed | None:
    """This block at the first start the rules accept, or nothing.

    The candidate starts are each roomy gap's own first grid point plus the starts of the block's
    own preferred windows inside it (:func:`starts_in`, window starts first), and the gaps run in
    :func:`_windows_around`'s order, the content's preferred ones first.
    """
    duration = held.block.interval.duration
    for window in _windows_around(held, rest, preferences):
        for start in starts_in(
            held.block.binding, held.block.area_id, window, preferences=preferences
        ):
            if start + duration > window.end:
                continue
            moved = _moved_to(held, start, rest)
            if moved is not None:
                return moved
    return None


def _swaps(attempt: Attempt, chosen: Sequence[Placed]) -> Iterator[Move]:
    """Every pair of chosen blocks of equal length, each placed at the other's interval.

    Only pairs of equal length: two blocks of different lengths exchanged would each need its
    neighbour's slack as well, which is a relocation of both and not a swap. Restricting the move
    keeps it decidable from the pair alone, and it is what makes the pass affordable: the pairs are
    grouped by length rather than filtered inside the loop, because at 150 blocks the quadratic scan
    was 2.6 s of a 2.5 s solve on its own.
    """
    for pairs in _by_length(chosen).values():
        for first in range(len(pairs)):
            for second in range(first + 1, len(pairs)):
                left, right = pairs[first], pairs[second]
                rest = _without(attempt, (left, right))
                moved = _exchanged(left, right, rest)
                if moved is not None:
                    yield Move(kind=SWAP, attempt=moved)


def _by_length(chosen: Sequence[Placed]) -> Mapping[int, tuple[Placed, ...]]:
    """These placements grouped by how long they are, in the order they arrived.

    Only a group of two or more can produce a swap, so the singletons are dropped: on the week this
    was measured against that is most of them.
    """
    grouped: dict[int, list[Placed]] = {}
    for held in chosen:
        grouped.setdefault(held.block.interval.total_minutes(), []).append(held)
    return {minutes: tuple(members) for minutes, members in grouped.items() if len(members) > 1}


def _exchanged(left: Placed, right: Placed, rest: Attempt) -> Attempt | None:
    """The plan holding each of these two blocks at the other's interval, or nothing.

    Each block keeps its own content and its own length, so this exchanges intervals rather than
    re-deriving what either block holds.
    """
    one = _moved_to(left, right.block.interval.start, rest)
    if one is None:
        return None
    with_one = rest.adding(one)
    other = _moved_to(right, left.block.interval.start, with_one)
    if other is None:
        return None
    return with_one.adding(other)


def _moved_to(held: Placed, start: Instant, rest: Attempt) -> Placed | None:
    """This block at a new start, keeping its length and its content, or nothing where a rule says.

    The length is the one it already holds, so the interval is built from the start rather than
    re-chosen: changing a length is the resize kind, and doing it here would make one move two.
    """
    if start == held.block.interval.start:
        return None
    moved = Placed.of(
        replace(held.block, interval=Interval(start, start + held.block.interval.duration)),
        sizing=held.placement.sizing,
        chosen=True,
    )
    return None if CHECK.check(moved.placement, rest.state) is not None else moved


def _windows_around(
    held: Placed, rest: Attempt, preferences: ResolvedPreferences
) -> tuple[Interval, ...]:
    """The gaps this block could move into, its own preferred ones first, long enough to hold it.

    A gap shorter than the block cannot hold it whatever else is true, so it is dropped before the
    checker is asked: the check is the expensive half. Where the block lands inside a gap is the
    caller's question -- :func:`_relocations` takes the gap's start plus the block's own preferred
    starts from each window this returns.
    """
    minutes = held.block.interval.total_minutes()
    roomy = tuple(gap for gap in rest.gaps() if gap.total_minutes() >= minutes)
    return preferred_first(held.block.binding, held.block.area_id, roomy, preferences)


def _resizes(
    attempt: Attempt, chosen: Sequence[Placed], preferences: ResolvedPreferences
) -> Iterator[Move]:
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
            for offer in offers_in(candidate, window, attempt=rest, preferences=preferences):
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
        # Only a piece the solve chose may be dropped. See `_chosen`: no rule refuses a re-placed
        # piece, because it takes a chunk number `state.immovable` cannot match.
        pieces = tuple(
            held for held in chosen if held.chosen and demand_key(held.block.binding) == key
        )
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
                for found in offers_in(current, window, attempt=rebuilt, preferences=preferences)
                if refusal_of(found, rebuilt) is None
            ),
            None,
        )
        if offer is None:
            return rebuilt if placed else None
        rebuilt = rebuilt.adding(offer.placed)
        placed = True


def _divided(chosen: Sequence[Placed]) -> tuple[DemandKey, ...]:
    """The tasks the solve holds a piece of, in the order their first piece was placed.

    ``chosen`` is filtered again rather than trusted, and it does two things. It keeps the pieces a
    re-split drops to the ones the solve chose, which is the property :func:`_chosen` explains; and
    it keeps a task whose only piece is pinned out of the keys, so the pieces the caller collects
    next are never empty.
    """
    found: list[DemandKey] = []
    for held in chosen:
        if not held.chosen or held.block.binding.kind is not BindingKind.TASK:
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
