"""Sorting a feed's components by the role each plays, and placing what each one produces.

Reading a feed and deciding what its components MEAN to each other are two jobs, and this is the
second. Four rules live here, and each exists because the alternative loses an hour of the user's
time or invents one.

**A cancelled master cancels its whole series, overrides included.** A replacement whose series the
feed cancelled has nothing live to attach to, so it places nothing. Deciding that by dictionary
membership instead would place it as a standalone event: a component the feed said does not happen
becoming hard occupancy, which is the inverse of the harm the cancellation rules exist to prevent.

**An override whose series is absent is an orphan, and it is placed.** An export window beginning
after a series did emits the moved occurrence and not the master, so this is a real publisher's
behavior rather than a broken feed. The feed asserts the commitment; dropping it loses an hour the
user is busy.

**An override no occurrence claims is counted, not placed.** A publisher that edits a series' rule
and keeps a previously emitted override produces one, and Google and Exchange exports both do. Every
such override has a master in the same body, so the series it belongs to did expand and its current
rule is what the feed asserts; placing the override as well would put a second event on an occupied
hour, which is what a duplicate master shifting the series' times produces. It is found by comparing
what was registered against what expansion actually consumed, so the answer depends on what the
parser DID rather than on what the partition guessed it would do.

**A tombstone that claims nothing is counted, not silently dropped.** It cancels an occurrence
nobody sent, so there is nothing to suppress, and a count is the only way the arithmetic can see it.
A REPEATED tombstone is counted the same way, for the same reason: a set would absorb it.

``applied`` is the thread through all of this: expansion reports which override keys it consumed, so
one number can mean "replacements that actually replaced something" rather than "replacements that
found a master".
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Final

from syncr_api.calendars.events import RawEvent
from syncr_api.calendars.ics_errors import MalformedValue
from syncr_api.calendars.ics_recurrence import occurrences
from syncr_api.calendars.ics_times import ONE_DAY, resolve, resolve_day_span, resolve_span
from syncr_domain.intervals import Interval

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from datetime import datetime

    from syncr_api.calendars.ics_components import EventComponent
    from syncr_domain.zones import ZoneProfile

# A replacement is found by the series it belongs to and the WALL TIME of the occurrence it
# replaces, which is the text a RECURRENCE-ID states and what makes one occurrence distinct from
# every other.
#
# It cannot be the instant, though matching has to reach across forms. Two occurrences of one
# series can share an instant: a wall time inside a spring-forward gap resolves onto the same
# instant as the real wall time an hour later, so an instant key named two occurrences at once.
# Measured, that placed one override twice and lost the other of a pair. Cross-form matching is a
# SECOND index instead: see ``Series.same_instant``.
type OccurrenceKey = tuple[str, datetime]

# Where a replacement is found when the publisher wrote the other form: the series, and the instant
# a key resolves onto. Spelled the same as an ``OccurrenceKey`` and meaning something else, so the
# two are named apart: this one holds an INSTANT where that one holds a WALL time.
type InstantKey = tuple[str, datetime]

# What a component sorted as a replacement always has, so a missing one is syncr's bug rather than
# the feed's. Named once because two sites assert it.
_NOT_A_REPLACEMENT: Final = "a component with no RECURRENCE-ID was sorted as a replacement"

_OCCURRENCE_STAMP = "%Y%m%dT%H%M%S"


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


@dataclass(frozen=True, slots=True)
class Placement:
    """What one component placed, and which replacement keys placing it consumed.

    ``applied`` is what lets a replacement's fate be decided by expansion rather than by the
    partition: a key nothing consumed named an occurrence the rule never produces.

    ``duplicates``, ``cancelled``, and ``resolved_away`` carry what cross-form precedence discarded
    while deciding which spelling of an occurrence stands. The losers are gone from the series' own
    registers by the time the partition compares what was registered against what expansion
    consumed, so each count travels with the placement that produced it instead of being guessed at
    afterwards.
    """

    events: tuple[RawEvent, ...] = ()
    applied: frozenset[OccurrenceKey] = frozenset()
    duplicates: int = 0
    cancelled: int = 0
    resolved_away: frozenset[OccurrenceKey] = frozenset()


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


def _across_forms(
    series: Series, master: EventComponent, produced: Iterable[datetime], *, profile: ZoneProfile
) -> tuple[Series, int, int, frozenset[OccurrenceKey]]:
    """Settle replacements of ONE occurrence that a body named in more than one legal form.

    RFC 5545 permits a ``RECURRENCE-ID`` as the occurrence's own wall time, as UTC, or in any named
    zone, so one edit can arrive twice under two spellings. Sorting resolves each spelling against
    its own key, which answers two bodies wrongly: two live spellings of one occurrence both
    survive, and the one matching the occurrence's wall wins whatever ``SEQUENCE`` says; a
    cancellation in the other form never meets the override it cancels. The keys have to compete.

    **The produced walls are what make the competition safe.** Two DISTINCT occurrences can share
    an instant -- a wall inside a spring-forward gap resolves onto the same instant as the real wall
    an hour later, and a skipped date folds a whole day forward -- so keys sharing an instant cannot
    simply be merged. What discriminates is how many of THIS series' own walls resolve onto the
    instant: one means every key here names THE occurrence, so they compete; two or more mean two
    occurrences share it and which spelling names which is the claiming question, answered at match
    time by :func:`_named_by` exactly as before.

    Runs per master rather than once per feed because the walls are a master's, and the answer for
    one series never touches another. The losers are dropped from the registers and returned as
    ``resolved_away`` keys, so the partition's comparison of registered against consumed cannot
    count them a second time; their discard counts travel back for the same reason.

    A feed with no cross-form index pays nothing: the early return is the ordinary body's path.
    """
    if not series.same_instant:
        return series, 0, 0, frozenset()
    instants = [resolve(master.start, profile, wall=wall) for wall in produced]
    overrides = dict(series.overrides)
    tombstones = dict(series.tombstones)
    duplicates = 0
    cancelled = 0
    resolved_away: set[OccurrenceKey] = set()
    for (uid, instant), keys in series.same_instant.items():
        if uid != master.uid or sum(1 for at in instants if at == instant) != 1:
            continue
        # Every spelling here names THE one occurrence this series produces on this instant, so the
        # group competes for a single slot. The entries are re-keyed onto that occurrence's own
        # wall before the rule runs: the rule compares what names one occurrence, and the survivor,
        # whichever spelling won, is held against the key matching will hit first.
        own_wall = next(wall for wall, at in zip(produced, instants, strict=True) if at == instant)
        own_key = (uid, own_wall)
        lives, tombs, group_duplicates, group_cancelled = _compete(
            (
                own_key,
                held if (held := overrides.get(key)) is not None else tombstones[key],
            )
            for key in keys
        )
        duplicates += group_duplicates
        cancelled += group_cancelled
        for key in keys:
            resolved_away.add(key)
        resolved_away.discard(own_key)
        for key, component in {**lives, **tombs}.items():
            if component.cancelled:
                tombstones[key] = component
            else:
                overrides[key] = component
    if not resolved_away:
        return series, duplicates, cancelled, frozenset()
    return (
        replace(
            series,
            overrides={key: item for key, item in overrides.items() if key not in resolved_away},
            tombstones={key: item for key, item in tombstones.items() if key not in resolved_away},
            same_instant={
                at: tuple(key for key in keys if key not in resolved_away)
                for at, keys in series.same_instant.items()
                if any(key not in resolved_away for key in keys)
            },
        ),
        duplicates,
        cancelled,
        frozenset(resolved_away),
    )


def expand(
    master: EventComponent, series: Series, *, horizon: Interval, profile: ZoneProfile
) -> Placement:
    """Every event one master component produces inside ``horizon``.

    An occurrence the feed cancelled produces nothing: the feed said it does not happen, and placing
    it would blank an hour the user actually has. Both a suppressed occurrence and a replaced one
    report their key as applied, because both are replacements that did their job.

    A replacement is placed at the time the REPLACEMENT states, so it can move an occurrence out of
    the horizon entirely. The occurrence generated it, but the event has to land in the window like
    any other, or a plan for February holds an anchor in August.

    Every event is filtered the same way, replacement or not. The expansion window is widened
    backwards by the series' length so an occurrence running INTO the horizon is found, which also
    finds one ending exactly AT it: the horizon is half-open, so that event occupies none of it and
    was an anchor one instant wide. Filtering only the replacements left the same position answered
    two ways depending on whether a publisher had moved it.
    """
    window = _window(horizon, master)
    recurring = master.recurrence.recurring
    built: list[RawEvent] = []
    applied: set[OccurrenceKey] = set()
    # Tuple rather than the expander's own iterator: the walls are walked twice, once into the set
    # a cross-form lookup reads and once by the loop that places each one.
    produced = tuple(occurrences(master.start, master.recurrence, window=window, profile=profile))
    # Every wall this master yields, so a cross-form lookup can tell a replacement that belongs to
    # ANOTHER occurrence of this same series from one that belongs to this occurrence written
    # differently. The same walls are what let precedence across the two legal RECURRENCE-ID forms
    # run before matching: see :func:`_across_forms`.
    walls = frozenset(produced)
    effective, merged_duplicates, merged_cancelled, resolved_away = _across_forms(
        series, master, produced, profile=profile
    )
    for wall in produced:
        key = _named_by(effective, master, wall, applied=applied, walls=walls, profile=profile)
        if key in effective.tombstones:
            applied.add(key)
            continue
        replacement = effective.overrides.get(key)
        if replacement is not None:
            applied.add(key)
        source = replacement or master
        span = interval_of(source, at=source.start.wall if replacement else wall, profile=profile)
        if not span.overlaps(horizon):
            continue
        built.append(
            RawEvent(
                uid=occurrence_uid(master.uid, wall) if recurring else master.uid,
                series_uid=master.uid if recurring else None,
                title=source.title,
                interval=span,
                location=source.location,
                sequence=source.sequence,
                all_day=source.all_day,
                transparent=source.transparent,
            )
        )
    return Placement(
        events=tuple(built),
        applied=frozenset(applied),
        duplicates=merged_duplicates,
        cancelled=merged_cancelled,
        resolved_away=resolved_away,
    )


def _named_by(
    series: Series,
    master: EventComponent,
    wall: datetime,
    *,
    applied: set[OccurrenceKey],
    walls: frozenset[datetime],
    profile: ZoneProfile,
) -> OccurrenceKey:
    """The replacement key this occurrence answers to, in the publisher's spelling or the other one.

    A ``RECURRENCE-ID`` matching this occurrence's own wall time is the ordinary case and is taken
    first. RFC 5545 also permits the UTC form, which names the same occurrence with different text,
    so a miss falls back to the keys sharing the instant this occurrence lands on.

    **A cross-form match is refused when the replacement's own wall is one this series produces.**
    Two occurrences can share an instant, because a wall time inside a spring-forward gap resolves
    onto the same instant as the real wall time after it, and a gap of a whole day exists too: Samoa
    skipped 30 December 2011 entirely. A replacement naming a wall the series DOES produce belongs
    to that occurrence, whichever of the two is expanded first.

    Whether the key was already applied is not the discriminator, because expansion order decides
    that: the gap wall always sorts BEFORE the real wall sharing its instant, so the earlier
    occurrence would take a replacement written for the later one and the later one would match its
    own key as well. What settles it is the produced walls, which do not depend on order.
    """
    exact = (master.uid, wall)
    if exact in series.overrides or exact in series.tombstones:
        return exact
    if not series.same_instant:
        # The ordinary feed: no replacement is written in the other form, so there is nothing to
        # look up and no reason to resolve this occurrence to an instant. Without this, every
        # occurrence of every series in every feed pays for a resolve only a cross-form body needs.
        return exact
    instant = resolve(master.start, profile, wall=wall)
    for other in series.same_instant.get((master.uid, instant), ()):
        if other not in applied and other[1] not in walls:
            return other
    return exact


def place_replacement(
    replacement: EventComponent, *, horizon: Interval, profile: ZoneProfile
) -> Placement:
    """The one event an ORPHANED replacement stands for, if it lands in the horizon.

    Placed rather than dropped, because no master in the body covers this commitment and the feed
    asserts it. Its identity is built from the wall time its own ``RECURRENCE-ID`` states, which is
    the same identity the series would give that occurrence WHEN THE TWO ARE WRITTEN IN THE SAME
    FORM, so a later sync carrying the master reconciles to the same anchor rather than creating a
    second one.

    Two limits on that, both measured, and neither fixable here:

    - A ``RECURRENCE-ID`` in the UTC form on a zoned series states a different wall time for the
      same occurrence, so its identity does not converge with the master's. An orphan has no master,
      so the zone the master expands in is not knowable at this point. Matching is answered across
      the two forms; identity cannot be.
    - Identity follows the wall time, so when two revisions of one master name one instant in
      different zones, the WINNER's zone decides the identity of every occurrence. A duplicate
      dropping out of a later export renames the whole series.
    - A NON-RECURRING master uses its bare uid, so an orphan of one gets an occurrence-shaped
      identity that master would not have given it.

    Both are recorded as known issues rather than papered over: the wall stamp is what a publisher
    sends again, and an identity derived from the instant instead would move with a zone database
    update.

    A replacement whose master IS present is not placed here: see :func:`stranded`.
    """
    span = interval_of(replacement, at=replacement.start.wall, profile=profile)
    if not span.overlaps(horizon):
        return Placement()
    return Placement(
        events=(
            RawEvent(
                uid=occurrence_uid(replacement.uid, replacement.replaces.wall)
                if replacement.replaces is not None
                else replacement.uid,
                series_uid=replacement.uid,
                title=replacement.title,
                interval=span,
                location=replacement.location,
                sequence=replacement.sequence,
                all_day=replacement.all_day,
                transparent=replacement.transparent,
            ),
        )
    )


def stranded(
    series: Series,
    applied: frozenset[OccurrenceKey],
    *,
    expanded: frozenset[str],
    horizon: Interval,
    profile: ZoneProfile,
) -> tuple[tuple[EventComponent, ...], int, int]:
    """What became of the replacements no occurrence claimed.

    A replacement is registered by UID and read by occurrence, so one naming a time the master's
    rule never produces is registered and never consulted. Comparing what expansion consumed against
    what was registered is the only way to see that, because the partition cannot know which
    occurrences a rule will produce.

    Two outcomes, and the discriminator is whether the master could have covered this hour at all.

    A replacement whose ORIGINAL time falls outside its master's expansion window was never offered
    to that master: the series did not decline it, the window simply did not reach it. It is handed
    back to be placed, exactly as an orphan is, because it may be an hour the user is busy that
    nothing else reports. Dropping it hides an occurrence a publisher moved forward into the window,
    and the plan books over it.

    A replacement whose original time WAS inside the window and still went unclaimed is superseded:
    the rule that would have produced it has changed, or a duplicate master shifted the series'
    times and this override belonged to the losing revision. Placing it as well puts two events on
    one occupied hour, so it is counted.

    ``expanded`` is why the premise is "a master that expanded" rather than "a master in the body".
    A master whose own values were refused places nothing, so nothing in the feed covers the hour
    its replacement names, which is the orphan rule's premise exactly. Reading presence instead made
    the answer depend on WHICH LAYER refused the master: a master with an unreadable zone never
    reaches the partition, so its replacement was sorted as an orphan and placed, while a master
    with an unexpandable rule does reach it, so its replacement was counted and the hour vanished.
    Same feed shape, two answers, decided by which property the publisher got wrong.

    **Whether the replacement's own span reaches the horizon is deliberately not decided here.**
    This function runs outside the boundary that turns a component's values into a rejection, so
    building a span here would put an overflow from a publisher's magnitude outside every catch in
    the package. The placement path already answers it, under that boundary, and counts a
    replacement that lands nowhere as read-and-placed-nothing: the same term this would have added
    it to.
    """
    by_uid = {master.uid: master for master in series.masters if master.uid in expanded}
    reachable: list[EventComponent] = []
    superseded = 0
    for key, replacement in series.overrides.items():
        if key in applied:
            continue
        owner = by_uid.get(replacement.uid)
        if _never_offered(replacement, owner, horizon=horizon, profile=profile):
            reachable.append(replacement)
            continue
        superseded += 1
    return tuple(reachable), superseded, len(series.tombstones.keys() - applied)


def _never_offered(
    replacement: EventComponent,
    master: EventComponent | None,
    *,
    horizon: Interval,
    profile: ZoneProfile,
) -> bool:
    """Whether this master's expansion could not have reached the occurrence at all.

    The window is this replacement's OWN master's, looked up by UID. One window for the whole feed
    would be some other master's, and a longer or shorter one changes the answer: the same three
    components then say two different things depending on the order they are declared in, which is
    the harm the duplicate-master tie-break exists to prevent.

    No master means none expanded to cover this hour, whether the master was absent or refused, so
    the answer is the orphan rule's: nothing declined it.

    A magnitude that cannot be resolved has already been refused where the component was read, so
    there is nothing to catch here.
    """
    # The second condition is the TYPE's, not the value's: `replaces_at` is optional on the
    # component and set for everything sorted as a replacement.
    if master is None or replacement.replaces_at is None:
        return True
    window = _window(horizon, master)
    return not (window.start <= replacement.replaces_at < window.end)


def replaced_key(replacement: EventComponent) -> OccurrenceKey:
    """The occurrence a replacement names, by the wall time its ``RECURRENCE-ID`` states.

    The wall time and not the instant, because two occurrences of one series can share an instant
    across a spring-forward gap while their wall times always differ. Matching across the two legal
    forms of a ``RECURRENCE-ID`` is done with a second index rather than by keying on the instant.
    """
    if replacement.replaces is None:  # pragma: no cover - only replacements reach here
        raise MalformedValue(_NOT_A_REPLACEMENT)
    return (replacement.uid, replacement.replaces.wall)


def occurrence_uid(uid: str, wall: datetime) -> str:
    """The identity of one occurrence of a series.

    A series expands into many events sharing one UID, and reconciliation is keyed on the UID, so
    each occurrence needs its own or the second would overwrite the first. The ORIGINAL wall time is
    what distinguishes them, which is also what a ``RECURRENCE-ID`` names, so a replacement that
    moves an occurrence keeps that occurrence's identity rather than becoming a second event.
    """
    return f"{uid}#{wall.strftime(_OCCURRENCE_STAMP)}"


def interval_of(source: EventComponent, *, at: datetime, profile: ZoneProfile) -> Interval:
    """The span one occurrence occupies, taken from whichever component defined it."""
    if source.all_day:
        return resolve_day_span(source.start, profile, wall=at, days=source.whole_days)
    return resolve_span(source.start, profile, wall=at, span=source.absolute_span)


def _window(horizon: Interval, master: EventComponent) -> Interval:
    """``horizon`` widened backwards by the event's own length.

    An occurrence that began before the horizon and runs into it is still occupancy the solver has
    to respect, so the lower bound has to reach back far enough to find it.
    """
    lead = ONE_DAY * master.whole_days if master.all_day else master.absolute_span
    return Interval(horizon.start - lead, horizon.end)
