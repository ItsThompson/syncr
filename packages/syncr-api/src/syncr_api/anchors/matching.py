"""Which type an anchor gets: the first rule that matches, and the override that outranks it.

Rules evaluate in ``rule_order`` and the first match wins. That is a deliberate choice over
"the most specific match", because specificity is not orderable without inventing a comparison
the user cannot see: a rule on a title and a rule on a source are not comparable, so the only
honest tie-break is the one the user authored.

A rule with neither member set matches everything. That is legal and it is not a mistake to
guard against: a type nothing matches is still reachable by hand, and a catch-all placed last
is how "anything else from this feed is a lecture" is expressed.

Matching is case-insensitive on the title, because a publisher's capitalization is not a fact
about the commitment. It is a plain substring test rather than a pattern, because a pattern
language on a rules table is a second thing to learn and to escape.

**An override outranks every rule, and it persists on the series.** Retyping one occurrence of a
recurring meeting is a statement about the meeting, so a daily standup is typed once rather than
250 times, and an occurrence arriving next month inherits it. The override is derived from the
occurrences the tenant already holds rather than kept in a table of its own, which means it
lives exactly as long as the series does: a series the source stops publishing entirely takes
its override with it, and a series that keeps publishing carries it forward on every sync.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from syncr_api.anchors.records import AnchorRecord, AnchorTypeId, AnchorTypeRecord
    from syncr_api.calendars.records import CalendarSourceId

# What one occurrence's override says about its series: the type it was retyped to, which is
# `None` when the user retyped it to no type at all. A series absent from the mapping was never
# overridden, which is a different answer from one present with a `None` value.
type SeriesOverrides = Mapping[str, AnchorTypeId | None]


def matches(anchor_type: AnchorTypeRecord, *, title: str, source_id: CalendarSourceId) -> bool:
    """Whether this type's rule matches a commitment with this title from this source.

    Every member the rule states has to hold. A rule stating none matches everything.
    """
    rule = anchor_type.specification
    if rule.match_source_id is not None and rule.match_source_id != source_id:
        return False
    if rule.match_title_contains is not None:
        return rule.match_title_contains.casefold() in title.casefold()
    return True


def first_match(
    types: Sequence[AnchorTypeRecord], *, title: str, source_id: CalendarSourceId
) -> AnchorTypeId | None:
    """The first type in rule order whose rule matches, or ``None``.

    ``None`` leaves the anchor untyped, which is opaque busy time with no shadow of any kind.
    syncr makes no assumption about a commitment the user has not classified.
    """
    for anchor_type in types:
        if matches(anchor_type, title=title, source_id=source_id):
            return anchor_type.id
    return None


def series_overrides(anchors: Iterable[AnchorRecord]) -> SeriesOverrides:
    """The override each overridden series carries, read off the occurrences that hold it.

    Later occurrences win when two disagree, which they can only do if a write landed between
    two syncs; taking the last in the given order makes the answer a function of the caller's
    ordering rather than of row layout, and the repository orders by start.
    """
    return {
        anchor.series_uid: anchor.anchor_type_id
        for anchor in anchors
        if anchor.type_overridden and anchor.series_uid is not None
    }
