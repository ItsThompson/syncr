"""Churn and proposal fit: what the user accepted, and what they corrected twice.

Two figures, one substrate, and both are stated over rows that are never pruned.

## The acceptance ratio counts BLOCK CHANGES the user resolved

A proposal is a bundle of changes: blocks the solver would move, blocks it would drop, and blocks it
would add over live ones. The user resolves them two ways, and both leave a permanent row.

| Resolved | The row | Counted as |
|---|---|---|
| Assented to | an ``approved`` revision, whose document differs from the one it
supersedes | every changed block, accepted |
| Overridden | an ``edit_events`` row, holding what the solver proposed and what the
user kept | one changed block, rejected |

**The denominator is EVERY PIN, which is broader than every proposal-class change resolved.** An
``edit_events`` row is written on every pin, so a pin on a block the solver never placed, and a
first manual placement, both count as an overridden change. Narrowing it needs the stored edit
context read for whether a solver placement was displaced, which ticket 1540 carries along with the
denominator question itself. What must not happen in the meantime is the ratio being described as
narrower than it is, which is why this paragraph is here and in the Product panel's description.

**The denominator is the changes the user RESOLVED, not the changes they were shown.** A proposal
replaced in the pending slot before anyone acted on it leaves no permanent row, because the slot is
one row per week replaced in place: it is not a fact and nobody agreed to it. So this ratio answers
"of the changes the user acted on, how many did they take" rather than "of every change ever
rendered". Ticket 1540 carries the alternative, which needs a fact table this schema does not have.
A ratio over a denominator that cannot be read is not a stricter metric; it is an absent one.

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

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from syncr_domain.identity import BindingRef
    from syncr_domain.intervals import Interval
    from syncr_domain.weeks import IsoWeek


def acceptance_ratio(*, accepted: int, overridden: int) -> float | None:
    """The share of resolved proposal-class changes the user accepted.

    ``None`` when the user resolved none, which is not the same as accepting none: a gauge set to
    zero for a quiet fortnight would read as the solver proposing nothing the user would take.
    """
    resolved = accepted + overridden
    return None if resolved == 0 else accepted / resolved


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
