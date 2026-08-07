"""How much rearrangement this user was shown, and how much of it they let stand.

Churn tolerance is the one parameter fitted from the plan's own history rather than from the outcome
log or the edit corpus alone: it needs both, because a rearrangement is what the revisions record
and an objection is what an edit records.

## What counts as one rearrangement

One consecutive pair of revisions of one week. The later revision put some blocks somewhere else,
and each block that moved is a move the user either let stand or pinned back. Moves and drops,
paired on the derived block id, which is the reading the objective's own churn term takes: an
ADDITION is not churn, because nothing the user was looking at was rearranged by placing something
new beside it.

**What this does NOT read is an approval.** A revision that superseded another is a rearrangement
the user was shown, whether or not they assented to it, and assent is a separate signal with its own
column owned elsewhere. Reading it here would make this fitter's corpus depend on a table this job
would then have to agree with about what approval means.
"""

from __future__ import annotations

from itertools import pairwise
from typing import TYPE_CHECKING

from syncr_domain.identity import block_id
from syncr_learning.observations import ChurnObservation

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from syncr_domain.weeks import IsoWeek
    from syncr_learning.facts import RecordedEdit, StoredRevision


def churn_observations(
    revisions: Sequence[StoredRevision], edits: Sequence[RecordedEdit]
) -> Iterable[ChurnObservation]:
    """One observation per rearrangement, in week order and then in the order they were produced.

    The overrides counted against a rearrangement are the edits made at or after the later revision
    and before the revision that followed it, which is the window in which that arrangement was what
    the user was looking at. An edit outside every window belongs to no rearrangement and is counted
    in none, which is the honest reading: it objected to an arrangement this corpus does not hold.
    """
    for week, ordered in sorted(_by_week(revisions).items()):
        for index, (earlier, later) in enumerate(pairwise(ordered)):
            followed = ordered[index + 2] if index + 2 < len(ordered) else None
            yield ChurnObservation(
                moves=moves_between(earlier, later),
                overridden=_overrides_in(edits, week=week, since=later, until=followed),
            )


def moves_between(earlier: StoredRevision, later: StoredRevision) -> int:
    """How many of ``earlier``'s blocks ``later`` put somewhere else or dropped."""
    before = {block_id(earlier.iso_week, one.binding): one.interval for one in earlier.blocks}
    after = {block_id(later.iso_week, one.binding): one.interval for one in later.blocks}
    return sum(1 for identity, interval in before.items() if after.get(identity) != interval)


def _by_week(revisions: Sequence[StoredRevision]) -> dict[IsoWeek, list[StoredRevision]]:
    grouped: dict[IsoWeek, list[StoredRevision]] = {}
    for revision in revisions:
        grouped.setdefault(revision.iso_week, []).append(revision)
    return {week: sorted(held, key=lambda one: one.created_at) for week, held in grouped.items()}


def _overrides_in(
    edits: Sequence[RecordedEdit],
    *,
    week: IsoWeek,
    since: StoredRevision,
    until: StoredRevision | None,
) -> int:
    return sum(
        1
        for edit in edits
        if edit.iso_week == week
        and edit.created_at >= since.created_at
        and (until is None or edit.created_at < until.created_at)
    )
