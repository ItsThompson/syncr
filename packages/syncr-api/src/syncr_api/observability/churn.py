"""Churn and proposal fit: what the user accepted, and what they corrected twice.

Two figures, one substrate, and both are stated over rows that are never pruned.

## The acceptance ratio counts BLOCK CHANGES the user resolved

A proposal is a bundle of changes: blocks the solver would move, blocks it would drop, and blocks it
would add over live ones. The user resolves them two ways, and both leave a permanent row.

| Resolved | The row | Counted as |
|---|---|---|
| Assented to | an ``approved`` revision, whose document differs from the one it
supersedes | every changed block, accepted |
| Overridden | an ``edit_events`` row on a block the solve placed, holding what the solver
proposed and what the user kept | one changed block, rejected |

**The overridden half counts only the edits that could have displaced a SOLVER PLACEMENT.** An
``edit_events`` row is written on every pin, and a pin on a block whose own source fixed its time
answers no proposal: the frame, a concrete template entry, an imported commitment and the two
blocks a commitment casts are all placed outside the solve, so an edit naming one of them is in
neither half. ``habit`` and ``task`` are the two origins the solve places, so those are the edits a
proposal can be rejected in. :func:`~syncr_domain.identity.is_placed_by_the_solver` states that
split for the whole application, so it is not a subset invented here.

**One case is still counted that a widened read would exclude: a pin in a week the solver never
touched.** A first manual placement of a habit or a task block is an edit on solver-placed content
with no proposal behind it, so it reaches the overridden half and the ratio reads low by it.
Excluding it needs to know whether a solve had placed that block, and nothing on the row answers
that: the stored context holds the state the edit was made in rather than the provenance of the
placement it replaced. The Product panel's description states the same two things, because an
operator reading the panel cannot read this file.

**The denominator is the changes the user RESOLVED, not the changes they were shown.** A proposal
replaced in the pending slot before anyone acted on it leaves no permanent row, because the slot is
one row per week replaced in place: it is not a fact and nobody agreed to it. So this ratio answers
"of the changes the user acted on, how many did they take" rather than "of every change ever
rendered". The alternative reading needs a fact table this schema does not have, and a ratio over a
denominator that cannot be read is not a stricter metric; it is an absent one.

## A re-pin is the strongest signal the weights are wrong

The user corrected the same placement twice, which means a solve moved it back after they had
already said where it goes. Every pin bumps the week's input version and enqueues a solve, so a
SECOND edit naming the same binding in the same week is by construction an edit after a solve:
nothing else can have moved the block in between. That is why the second edit is the whole
definition and no comparison against a solve's own instant is needed.

The figure is per week rather than per period, because "re-pins per week, trending down" is what the
target is stated as, so the period's count is divided by the weeks in it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_domain.identity import is_placed_by_the_solver

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from syncr_domain.identity import BindingRef, Origin
    from syncr_domain.intervals import Interval
    from syncr_domain.weeks import IsoWeek


def acceptance_ratio(*, accepted: int, overridden: int) -> float | None:
    """The share of resolved proposal-class changes the user accepted.

    ``None`` when the user resolved none, which is not the same as accepting none: a gauge set to
    zero for a quiet fortnight would read as the solver proposing nothing the user would take.
    """
    resolved = accepted + overridden
    return None if resolved == 0 else accepted / resolved


def overridden_count(origins: Iterable[Origin]) -> int:
    """How many of these edits could have displaced a placement the solve chose.

    Read over one edit's origin each, rather than over the rows, because which rows exist is the
    re-pin count's question too and that count reads every pin.
    """
    return sum(1 for origin in origins if is_placed_by_the_solver(origin))


def changed_block_count(live: Mapping[str, Interval], candidate: Mapping[str, Interval]) -> int:
    """How many blocks differ between two plans, keyed by the derived block id each holds.

    Three classes, and each is one change: a block only the candidate holds, a block only the live
    plan holds, and a block both hold at different times. A block id is a digest of the week and the
    binding, so pairing on it is what makes "the same content" decidable with no lookup, and a MOVE
    keeps its id: a comparison over ids alone would see no move at all, which is the whole class the
    authority rule exists for.
    """
    moved = sum(1 for block_id, placed in live.items() if candidate.get(block_id, placed) != placed)
    return len(set(live) ^ set(candidate)) + moved


def repin_count(edits: Iterable[tuple[IsoWeek, BindingRef]]) -> int:
    """Edits that are not the first for their week and binding, oldest first."""
    seen: set[tuple[str, BindingRef]] = set()
    repinned = 0
    for iso_week, binding in edits:
        identity = (str(iso_week), binding)
        if identity in seen:
            repinned += 1
        else:
            seen.add(identity)
    return repinned
