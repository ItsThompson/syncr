"""Repeated collisions: one commitment meeting one block, week after week.

``US-REV-05``: the weekly session raises a repeated collision when the same commitment and the same
binding have conflicted in three or more weeks, naming the commitment, the block, and the number of
weeks -- ``repeated collision: Standup over Leetcode, 4 weeks``.

**It is informational and suggests no action**, which is why nothing here produces one. The fix
could be a template change, an anchor-type change, or nothing at all, and the product does not know
which: offering a remedy it cannot choose between would be worse than stating the pattern.

## Both halves of the key are stored on the row, and neither could be derived

``block_id`` is a digest of the week and the binding, so four collisions with one task in four weeks
hold four unrelated ids: revision ``0039_conflicts`` denormalized ``binding`` for exactly this. And
``anchor_id`` names one OCCURRENCE, so a weekly meeting holds a distinct id per week and the row's
own anchor has usually been deleted by the time the pattern exists, because reconciliation drops an
occurrence its feed no longer publishes. Revision ``0051_conflict_commitments`` denormalized
``series_uid`` for that, and the title beside it, because a label read from a deleted row is no
label at all.

## A commitment with no series never contributes, and that is the rule rather than a gap

A one-off cannot recur, so a row carrying no ``series_uid`` is not part of any pattern. This also
covers a row raised before the series was recorded: it says the commitment is not comparable across
weeks, which is exactly what such a row means.

## The count is a count of WEEKS, and they need not be consecutive

The story's words are "three or more weeks", which is deliberately weaker than the consecutive run
a repeated pin and a chronic skip are stated over. A collision the user resolved one week and met
again two weeks later is the same pattern: the commitment did not stop landing there, and a gap in
the middle is often the resolution that did not hold rather than evidence against the pattern.

Two conflicts in one week for one pair count once. Detection runs at ingest on every sync and again
on every solve's commit path, and a resolution of ``moved`` or ``retyped`` deliberately allows the
same pair to be raised again, so rows are not a measure of anything the user experienced.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from syncr_api.plans.records import ConflictRecord
    from syncr_domain.identity import BindingKind, BindingRef
    from syncr_domain.weeks import IsoWeek

    # The pair a repetition is grouped by: the commitment's series, and the block's content with its
    # week-scoped occurrence dropped.
    type CollisionKey = tuple[str, BindingKind, UUID, int | None]


@dataclass(frozen=True, slots=True, kw_only=True)
class RepeatedCollision:
    """One commitment and one block that keep meeting.

    ``commitment`` is the name the commitment carried when the most recent of these overlaps was
    raised, or ``None`` for a run of rows raised before any of them recorded one. ``weeks`` is every
    ISO week the pair met in, oldest first, so the raise states its count from the data.
    """

    commitment: str | None
    binding: BindingRef
    weeks: tuple[IsoWeek, ...]

    @property
    def week_count(self) -> int:
        """How many weeks this commitment and this block met in."""
        return len(self.weeks)


def repeated_collisions(
    conflicts: Sequence[ConflictRecord], *, at_least_weeks: int
) -> list[RepeatedCollision]:
    """Every commitment-and-block pair that met in at least ``at_least_weeks`` weeks.

    Most weeks first, then by commitment name, so the pattern the user has lived with longest is the
    one they read first.

    ``conflicts`` is whatever bounded page the caller read, in any order. Resolved rows are what
    make this computable at all: a conflict is retained rather than deleted when it is answered. An
    unanswered one counts too, because the pattern includes the week nobody has answered for yet.
    """
    grouped: dict[CollisionKey, set[IsoWeek]] = {}
    named: dict[CollisionKey, tuple[str | None, BindingRef, IsoWeek]] = {}
    for conflict in conflicts:
        if conflict.series_uid is None:
            continue
        kind, entity_id, split_index = conflict.binding.content_key
        key = (conflict.series_uid, kind, entity_id, split_index)
        grouped.setdefault(key, set()).add(conflict.iso_week)
        newest = named.get(key)
        if newest is None or newest[2] < conflict.iso_week:
            named[key] = (conflict.commitment_title, conflict.binding, conflict.iso_week)
    found = []
    for key, weeks in grouped.items():
        if len(weeks) < at_least_weeks:
            continue
        commitment, binding, _newest = named[key]
        found.append(
            RepeatedCollision(commitment=commitment, binding=binding, weeks=tuple(sorted(weeks)))
        )
    return sorted(found, key=lambda one: (-one.week_count, one.commitment or ""))
