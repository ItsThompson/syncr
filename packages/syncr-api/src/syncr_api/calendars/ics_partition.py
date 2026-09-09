"""Sorting a feed's components by the role each plays.

Deciding what its components MEAN to each other is this module's one job. A component is a master,
a replacement, or an orphan, and which it is decides where the surviving ones land: see
:mod:`syncr_api.calendars.ics_placement`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from syncr_api.calendars.ics_errors import MalformedValue

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from datetime import datetime

    from syncr_api.calendars.ics_components import EventComponent

# An OccurrenceKey is the series a replacement belongs to and the WALL TIME of the occurrence it
# replaces, which is the text a RECURRENCE-ID states and what makes one occurrence distinct from
# every other. It cannot be the instant: two occurrences of one series can share an instant, so an
# instant key would name two at once. The two cases that make two walls share one instant:
# - A spring-forward gap: a wall inside the gap resolves onto the same instant as the real wall an
#   hour later.
# - A skipped date: Samoa skipped 30 December 2011 entirely, so a daily rule's wall on the 30th
#   resolves onto the same instant as its wall on the 31st.
#
# What matches an OccurrenceKey: the key itself when the publisher wrote the same form, and a
# SECOND index (``Series.same_instant``) when the publisher wrote the other legal form. The index
# is built here; the match is claimed at the placement by the walls the series produces: see
# :func:`ics_placement._named_by`.
type OccurrenceKey = tuple[str, datetime]

# Where a replacement is found when the publisher wrote the other form: the series, and the instant
# a key resolves onto. Spelled the same as an ``OccurrenceKey`` and meaning something else, so the
# two are named apart: this one holds an INSTANT where that one holds a WALL time.
type InstantKey = tuple[str, datetime]

# What a component sorted as a replacement always has, so a missing one is syncr's bug rather than
# the feed's. Named once because two sites assert it.
_NOT_A_REPLACEMENT: Final = "a component with no RECURRENCE-ID was sorted as a replacement"


@dataclass(frozen=True, slots=True)
class Series:
    """A feed's components sorted by role, and the discards that sorting produced.

    ``tombstones`` is why this is a struct rather than a tuple of six things. A cancelled component
    is one of two entirely different statements depending on whether it carries a ``RECURRENCE-ID``,
    and conflating them is how a cancelled occurrence ends up in the plan.

    ``cancelled`` counts every component a cancellation discarded, whichever form it took: a
    cancelled master, a tombstone whose series is absent, a replacement of a series the feed
    cancelled, and an override a tombstone on the same occurrence displaced -- in either spelling of
    that occurrence, since a body may name one occurrence in more than one legal ``RECURRENCE-ID``
    form. Each places nothing, and each needs counting or it vanishes from the arithmetic.
    :func:`parse_feed` adds one more form to the reported total, a tombstone no occurrence claimed,
    so a caller's field holds five.
    """

    masters: tuple[EventComponent, ...] = ()
    overrides: Mapping[OccurrenceKey, EventComponent] = field(default_factory=dict)
    # A key per cancelled occurrence, mapped to the component that cancelled it. The component is
    # kept so precedence between the two legal spellings of one occurrence can be settled after
    # sorting, where a tombstone competes with a live override it was sorted beside.
    tombstones: Mapping[OccurrenceKey, EventComponent] = field(default_factory=dict)
    same_instant: Mapping[InstantKey, tuple[OccurrenceKey, ...]] = field(default_factory=dict)
    orphans: tuple[EventComponent, ...] = ()
    duplicates: int = 0
    cancelled: int = 0


def sort_components(readable: list[EventComponent]) -> Series:
    """Sort a feed's components into masters, replacements, orphans, and discards.

    **Cancellation is read after the role, not before it.** A cancelled MASTER cancels the event; a
    cancelled REPLACEMENT cancels one occurrence of a series that is otherwise live, which is how
    Exchange and most CalDAV servers express a deleted occurrence. Filtering cancellations first
    makes the second look like the absence of a replacement, so the master's own occurrence is
    emitted and the feed's cancelled hour stays in the plan as hard occupancy.

    Two components with one UID and no ``RECURRENCE-ID`` are the duplicate case. The higher
    ``SEQUENCE`` wins, and an equal ``SEQUENCE`` keeps the LIVE one, so the answer does not depend
    on the order a dictionary happens to hold. **Two replacements of the same occurrence resolve by
    ``SEQUENCE`` too**, because an overlapping export repeats an override as readily as it repeats
    a master, but there a cancellation wins outright rather than by revision: see :func:`_resolve`.
    Two CANCELLED replacements of one occurrence say the same thing, so there is nothing to resolve,
    but the second is still counted rather than absorbed.
    """
    masters: dict[str, EventComponent] = {}
    replacements: list[EventComponent] = []
    duplicates = 0
    cancelled = 0
    for candidate in readable:
        if candidate.replaces is not None:
            replacements.append(candidate)
            continue
        held = masters.get(candidate.uid)
        if held is None:
            masters[candidate.uid] = candidate
            continue
        # Two revisions of one series. The higher SEQUENCE wins WHETHER OR NOT either is cancelled:
        # reading the cancellation first would let an older live revision beat the cancellation that
        # superseded it, and place a whole series the feed's latest word says does not happen.
        #
        # At EQUAL SEQUENCE the live one wins, rather than whichever was declared first. Most
        # publishers emit no SEQUENCE at all, so a tie is the common case, and letting document
        # order decide made the same three components answer two ways: declare the cancelled
        # duplicate first and a whole live series with its moved hour disappeared, with the
        # accounting closing over the loss. Preferring the live one is the safe direction, because
        # the alternative deletes occupancy the feed also asserts.
        duplicates += 1
        if (candidate.sequence, not candidate.cancelled) > (held.sequence, not held.cancelled):
            masters[candidate.uid] = candidate

    live = {uid: master for uid, master in masters.items() if not master.cancelled}
    cancelled_uids = masters.keys() - live.keys()
    cancelled += len(cancelled_uids)

    attached: list[EventComponent] = []
    stray: list[EventComponent] = []
    for replacement in replacements:
        if replacement.uid in live:
            attached.append(replacement)
        elif replacement.uid in cancelled_uids:
            # The series this replaces is cancelled, so there is nothing live to attach it to and
            # nothing it could be an occurrence OF. Placing it would turn a cancellation into
            # occupancy.
            cancelled += 1
        else:
            stray.append(replacement)

    # The same precedence applies whether or not the master is present, so it is resolved once. What
    # differs is what happens to the survivors: a replacement of a live series is read against that
    # series' occurrences, while one of an absent series is placed on its own.
    held_by_a_series = _resolve(attached)
    orphaned = _resolve(stray)
    duplicates += held_by_a_series.duplicates + orphaned.duplicates
    cancelled += held_by_a_series.cancelled + orphaned.cancelled
    # An orphaned tombstone cancels an occurrence nobody sent, so it has nothing to suppress and a
    # count is the only way the arithmetic sees it. One that DID suppress an orphan is already
    # counted by `_resolve`.
    cancelled += len(orphaned.tombstones)

    return Series(
        masters=tuple(live.values()),
        overrides=held_by_a_series.overrides,
        tombstones=held_by_a_series.tombstones,
        same_instant=held_by_a_series.same_instant,
        orphans=tuple(orphaned.overrides.values()),
        duplicates=duplicates,
        cancelled=cancelled,
    )


@dataclass(frozen=True, slots=True)
class _Resolved:
    """Replacements of one group, resolved to at most one per occurrence."""

    overrides: dict[OccurrenceKey, EventComponent]
    tombstones: dict[OccurrenceKey, EventComponent]
    same_instant: dict[InstantKey, tuple[OccurrenceKey, ...]]
    duplicates: int
    cancelled: int


def _resolve(replacements: Iterable[EventComponent]) -> _Resolved:
    """One replacement per occurrence, and a count of everything that lost.

    The rules hold whether or not the series these replace is present, which is why this is one
    function rather than two branches that drifted apart:

    - Two live replacements of one occurrence resolve by ``SEQUENCE``, tie to the first declared,
      and the loser is counted. An overlapping export repeats an override as readily as a master.
    - A repeated cancellation has no ``SEQUENCE`` question, both say the same thing, but the second
      is still counted or a set absorbs it and the arithmetic loses a component.
    - A cancellation beats a replacement of the same occurrence, because the feed's cancellation is
      what it means, and the override it displaces is counted rather than dropped silently.

    That last rule is deliberately NOT the master rule, where a cancellation wins only on a higher
    or equal ``SEQUENCE``. Here it wins outright. Most publishers emit no ``SEQUENCE`` at all, so
    the common case is a tie either way, and on a tie both rules agree: the cancellation holds. They
    part only when a cancelled override carries a LOWER ``SEQUENCE`` than a live one, where this
    keeps the hour clear. Refusing to place an hour the feed cancelled somewhere is the safe
    direction, because the alternative is immovable occupancy the user was told does not happen.

    ``same_instant`` is built alongside: the instant each surviving key names, so an occurrence can
    find a replacement written in the other legal form. It is an INDEX and not the key, because
    several keys can share one instant: see :func:`_by_instant`.
    """
    ordered = list(replacements)
    instants: dict[OccurrenceKey, datetime] = {}
    for replacement in ordered:
        # `replaces_at` is optional on the component because most components have no RECURRENCE-ID,
        # but anything sorted as a replacement carries one, so this cannot be None here and the
        # check is the type's rather than the value's. Falling back to `key[1]` would be worse than
        # raising: that is a WALL time, and it would sit in an index of instants where no lookup can
        # match it.
        if replacement.replaces_at is None:  # pragma: no cover - only replacements reach here
            raise MalformedValue(_NOT_A_REPLACEMENT)
        instants[replaced_key(replacement)] = replacement.replaces_at
    overrides, tombstones, duplicates, cancelled = _compete(
        (replaced_key(replacement), replacement) for replacement in ordered
    )
    return _Resolved(
        overrides=overrides,
        tombstones=tombstones,
        same_instant=_by_instant(instants),
        duplicates=duplicates,
        cancelled=cancelled,
    )


def _compete(
    entries: Iterable[tuple[OccurrenceKey, EventComponent]],
) -> tuple[dict[OccurrenceKey, EventComponent], dict[OccurrenceKey, EventComponent], int, int]:
    """The ONE precedence rule, applied to whatever components compete for occurrences.

    Entries are ``(key, component)`` pairs; components naming different keys never interact, so a
    caller may hand replacements of several occurrences at once. Returns the live survivors, the
    tombstones with the components that cancelled them, and the two discard counts the losers cost:

    - Two live replacements of one key resolve by ``SEQUENCE``, tie to the first declared.
    - A repeated cancellation is counted rather than absorbed by the set of keys held.
    - A cancellation beats a live replacement outright, and the override it displaces is counted.
      See :func:`_resolve` for why outright rather than on ``SEQUENCE``.

    Both resolution sites -- :func:`_resolve` at sorting time and :func:`_across_forms` where the
    produced walls have reached precedence -- drive THIS loop, so the rule cannot drift between the
    spelling a body declares an occurrence in and the one it does not.
    """
    overrides: dict[OccurrenceKey, EventComponent] = {}
    tombstones: dict[OccurrenceKey, EventComponent] = {}
    duplicates = 0
    cancelled = 0
    for key, replacement in entries:
        if replacement.cancelled:
            if key in tombstones:
                duplicates += 1
                continue
            tombstones[key] = replacement
            continue
        held = overrides.get(key)
        if held is None:
            overrides[key] = replacement
            continue
        duplicates += 1
        if replacement.sequence > held.sequence:
            overrides[key] = replacement

    for key in tombstones.keys() & overrides.keys():
        del overrides[key]
        cancelled += 1
    return overrides, tombstones, duplicates, cancelled


def _by_instant(
    instants: Mapping[OccurrenceKey, datetime],
) -> dict[InstantKey, tuple[OccurrenceKey, ...]]:
    """Every key, grouped by its series and the instant it resolves onto.

    EVERY key on an instant rather than one, because how many can share an instant is not bounded at
    two. A wall time inside a gap resolves onto the same instant as the real wall time after it, a
    ``RECURRENCE-ID`` in the UTC form states a third wall for that instant, and one naming any other
    zone states a fourth. One key per instant leaves the rest unreachable, and makes a body's answer
    depend on which of them the publisher declared last.

    Ordered by wall time rather than by declaration, so a lookup answers from the keys a body
    declares and not from the order it declares them in.

    Every key handed here survived sorting, because a replacement is recorded against a key that is
    then held as an override or as a tombstone, and a repeated one is counted against a key already
    held. Filtering for that again cannot exclude anything, so the invariant is crossed in the test
    that reports it rather than asserted by a condition no input can fail.
    """
    grouped: dict[InstantKey, list[OccurrenceKey]] = {}
    for key, instant in instants.items():
        grouped.setdefault((key[0], instant), []).append(key)
    return {at: tuple(sorted(keys, key=_wall_of)) for at, keys in grouped.items()}


def _wall_of(key: OccurrenceKey) -> datetime:
    return key[1]


def replaced_key(replacement: EventComponent) -> OccurrenceKey:
    """The occurrence a replacement names, by the wall time its ``RECURRENCE-ID`` states.

    The wall time and not the instant, because two occurrences of one series can share an instant
    across a spring-forward gap while their wall times always differ. Matching across the two legal
    forms of a ``RECURRENCE-ID`` is done with a second index rather than by keying on the instant.
    """
    if replacement.replaces is None:  # pragma: no cover - only replacements reach here
        raise MalformedValue(_NOT_A_REPLACEMENT)
    return (replacement.uid, replacement.replaces.wall)
