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

from syncr_api.reviews.naming import (
    a_kind,
    content_key_text,
    most_recently,
    weeks_stated,
)
from syncr_api.reviews.raised import RaisedItem, RaisedKind

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from uuid import UUID

    from syncr_api.plans.records import ConflictRecord
    from syncr_domain.identity import BindingKind, BindingRef
    from syncr_domain.weeks import IsoWeek

    # The pair a repetition is grouped by: the commitment's series, and the block's content with its
    # week-scoped occurrence dropped.
    type CollisionKey = tuple[str, BindingKind, UUID, int | None]

    # What `BindingRef.content_key` answers, which is what a block title is looked up by.
    type ContentKey = tuple[BindingKind, UUID, int | None]


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


def repeated_collision_items(
    collisions: Iterable[RepeatedCollision], *, titles: Mapping[ContentKey, str]
) -> list[RaisedItem]:
    """One item per pair that keeps meeting, in the form ``US-REV-05`` writes out.

    The story's own example is ``repeated collision: Standup over Leetcode, 4 weeks``, so the item
    names BOTH ends and the count: ``Standup over Leetcode`` as the title, and the two names again
    in the sentence that carries the count and the week it last happened in.

    **The block's name comes from a block, because nothing else holds one.** A conflict row stores
    the binding it collided with and no title, so ``titles`` is the window's own blocks keyed by
    content: see :func:`syncr_api.reviews.raised.block_titles`. A pair whose block no week of the
    window holds falls back to the binding's own word, which is the one fallback every surface of
    this payload takes.

    **A pair that can name NEITHER end is not raised at all.** One name is a raise the reader can
    act on: the block alone says which part of their own week keeps being interrupted, and the
    commitment alone says what keeps interrupting. Neither says only that something collided with
    something, which is not a pattern anybody can look into, and this raise suggests no action to
    make up the difference. That state is reachable rather than hypothetical: a conflict whose
    anchor had already gone when the solve committed carries no commitment, and a block no week of
    the window holds has no title.
    """
    items = []
    for collision in collisions:
        named = titles.get(collision.binding.content_key)
        if named is None and collision.commitment is None:
            continue
        block = a_kind(collision.binding.kind) if named is None else named
        items.append(
            RaisedItem(
                key=f"{RaisedKind.REPEATED_COLLISION}:{content_key_text(collision.binding)}",
                kind=RaisedKind.REPEATED_COLLISION,
                title=_titled(collision, block=block),
                statement=_collision_statement(collision, block=block),
            )
        )
    return items


def _titled(collision: RepeatedCollision, *, block: str) -> str:
    """The pair, or the one end that is nameable."""
    if collision.commitment is None:
        return block
    return f"{collision.commitment} over {block}"


def _collision_statement(collision: RepeatedCollision, *, block: str) -> str:
    """What the pair has done, naming both ends, the count of weeks, and when it last happened."""
    weeks = weeks_stated(collision.week_count)
    unnamed = f"An imported commitment has landed on {block} in {weeks}."
    named = f"{collision.commitment} has landed on {block} in {weeks}."
    return (
        f"{unnamed if collision.commitment is None else named}"
        f"{most_recently(collision.weeks)} Stated rather than acted on: the fix could be a "
        "template change, an anchor type, or nothing."
    )
