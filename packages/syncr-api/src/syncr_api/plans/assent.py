"""What an approval may change about the live plan, and what nobody assented to.

An approval writes a document the user was shown. What they were shown ALONGSIDE it is the
proposal diff, which names every change the plan of record would take: this module is the
comparison that keeps those two sets the same at the instant the write happens.

The gap it closes is one of timing. A proposal is classified against the live plan as it stood
when the solve ran, and approval happens later, so anything that advanced the live plan in
between is a change the approved document would also make and no diff ever named. The
auto-application is the case that produces it without any defect: a task captured into a free
gap appends an ``applied`` revision, the slot still holds a proposal computed before that
block existed, and approving it would drop the block with nothing scheduled to put it back.

```
 live plan L, slot holds P (P moves Gym, diff says: moved Gym)
 a task lands in a free gap        ──▶ applied revision. The live plan is L + fill
 the user approves P
      re-classified against L + fill: moved Gym, AND removed fill
      the diff named the move and never named the removal        ──▶ refused
```

## Additions are exempt, and that is the authority rule rather than an omission

Syncr may add without asking, so a block the document holds that the live plan does not is not
a change anybody has to have assented to. A block that ARRIVES over something is a different
matter, and it needs no rule here: the block it displaces is either moved or dropped by the same
document, and both of those are reported.

The candidate that filled the slot may itself have carried fills, which the diff does not hold
(the authority rule holds such a candidate whole, so its fills waited with its moves). Refusing
an addition the diff does not name would therefore refuse every proposal that had one.

## The past is compared here too, because this is the write

:func:`~syncr_api.plans.authority.classify` refuses a candidate that restates the week's own
past, and it did so when the solve ran. By approval time more of the week has elapsed, so the
document is compared again, against the instant it is actually being written at. Reusing
``classify`` is what keeps the two comparisons one rule: whichever origins the past binds, and
whatever a solve is exempted from, an approval is exempted from identically.

What is discarded from the re-classification is its conflict detection. An overlap between the
approved document and an imported commitment is already raised by the solve that produced it,
and raising it a second time here would ask the user the same question twice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.plans.authority import classify

if TYPE_CHECKING:
    from syncr_domain.intervals import Instant
    from syncr_domain.plan import PlanDocument
    from syncr_domain.proposals import BlockChange, ProposalDiff


def unassented_changes(
    live: PlanDocument | None,
    document: PlanDocument,
    shown: ProposalDiff,
    *,
    now: Instant,
) -> tuple[BlockChange, ...]:
    """The blocks ``document`` would move or drop that ``shown`` never named, newest last.

    ``live`` is ``None`` for a week whose plan of record does not exist yet, and such a week has
    nothing to move and nothing to drop, so nothing can be changed without assent.

    A change is exempt when the proposal named the same block AND left it in the same place, which
    is what the pair below is: the block, and where the change puts it. Pairing on the block alone
    would let a proposal that said "this moves to Thursday" exempt a document that drops it, and
    this module's whole job is to be the guard that trusts no earlier comparison. A removal states
    no placement, so it pairs only with a removal.

    Raises :class:`~syncr_api.plans.errors.ClassificationRejected` when the document restates a
    part of the week that has elapsed since it was produced. That is a different refusal with a
    different remedy, so it stays an exception rather than becoming a member of this list.
    """
    if live is None:
        return ()
    asked_about = {(change.block_id, change.after) for change in shown.changes()}
    diff = classify(live, document, now=now).proposal_diff
    return tuple(
        change
        for change in (*diff.removed, *diff.moved)
        if (change.block_id, change.after) not in asked_about
    )
