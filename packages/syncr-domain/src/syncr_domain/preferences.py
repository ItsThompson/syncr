"""The Preference: when an Area's, a Habit's, or a Task's work should happen.

One entity with a polymorphic owner rather than three near-identical shapes, because the
rules below are the same rules whichever of the three declared it, and three statements of
them would be three chances to disagree.

A preference is the sole expression of the placement-window physics: ``Gym`` occurs at 05:30
or 13:15, never 20:00. Nothing else in the product carries a preferred time. A habit and a
task each carry none, so each inherits its Area's windows unless it declares its own.

Five rules, and the first three are what this module exists to make unrepresentable.

**A strength is ``strong`` or ``soft``, never hard.** Both are components of the solver's
time-of-day misfit cost, differing by an order of magnitude in weight, so neither can leave a
block unscheduled. A hard temporal rule with a conditional escape is not a hard rule and no
property test can be written for one, which is why the enum has two members and no third is
coming.

**A daily cap belongs to an Area and to nothing else.** It is the one hard element a
preference is adjacent to, and it reaches the solver as the Area budget's own
``max_per_day_minutes`` rather than through the resolved preference. Confining the field to an
Area owner is therefore what structurally prevents an override relaxing a hard cap: there is
no shape here that could carry one.

**An override replaces wholly, never field by field.** :func:`preference_in_effect` returns
one preference out of a chain rather than merging two, so a habit that declares no ideal
duration has none, even when its Area declares one. That is the whole reason the routes are
``PUT`` rather than ``PATCH``: there is no merge rule to express.

**A preference captured from a slot on the grid is always soft.** :func:`captured_from_slot`
takes no strength, so a pin made for UI convenience cannot fabricate a strong training label
the learning layer would then fit against.

**A window's bounds land on the quarter hour.** Whether a user-chosen wall time owes the
fifteen-minute grid is an open product question, held from opposite sides by tickets 1151 and
1161; this module implements the side that says it does, and states why at the refusal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from enum import StrEnum
from itertools import pairwise
from typing import TYPE_CHECKING, Final

from syncr_domain.budgets import MINUTES_PER_HOUR
from syncr_domain.errors import DomainError
from syncr_domain.snap import SNAP_MINUTES, is_a_snap_multiple, is_wall_time_on_snap_grid

if TYPE_CHECKING:
    from syncr_domain.identifiers import AreaId, HabitId, TaskId
    from syncr_domain.zones import LocalTime

# Past a handful of named times of day a preference stops discriminating between them, and
# "anytime" is expressed by declaring no preference at all rather than by naming every hour.
MAX_WINDOWS: Final = 6

MINUTES_IN_A_DAY: Final = 24 * MINUTES_PER_HOUR

# :class:`LocalTimeWindow` states what an end of this value means and why it is the one bound that
# may read earlier than the start it belongs to.
END_OF_DAY: Final = time(0, 0)

# A session shorter than one grid step cannot be a block at all.
MIN_PREFERRED_DURATION_MINUTES: Final = SNAP_MINUTES
# Longer than a day, an ideal session length stops describing a session.
MAX_PREFERRED_DURATION_MINUTES: Final = MINUTES_IN_A_DAY

# A cap below one grid step admits no block whatsoever, which says "never" rather than "at
# most this much". Never is a forbidden Area, not a cap.
MIN_MAX_PER_DAY_MINUTES: Final = SNAP_MINUTES
# A cap of a whole day is the widest one that still caps anything.
MAX_MAX_PER_DAY_MINUTES: Final = MINUTES_IN_A_DAY


def _minutes_from_midnight(bound: LocalTime) -> int:
    """``bound`` as a count of minutes, which is the coordinate two bounds are compared in."""
    return bound.hour * MINUTES_PER_HOUR + bound.minute


class PreferenceStrength(StrEnum):
    """How much violating a preferred window costs. Two members, and never a third.

    Both are objective components rather than constraints, so neither can leave a block
    unscheduled. ``STRONG`` costs an order of magnitude more to violate than ``SOFT``.
    """

    STRONG = "strong"
    SOFT = "soft"


class PreferenceOwnerKind(StrEnum):
    """Which of the three things a preference is attached to."""

    AREA = "area"
    HABIT = "habit"
    TASK = "task"


class PreferenceField(StrEnum):
    """The field a rejection names, spelled as the entity's own field names.

    Carried on the error, so the mapping from a refusal to a field is the refusal itself
    rather than a table elsewhere that a fifth field would have to be added to.
    """

    WINDOWS = "windows"
    PREFERRED_DURATION = "preferred_duration_minutes"
    MAX_PER_DAY = "max_per_day_minutes"


class PreferenceError(DomainError):
    """A preference's invariants reject the given declaration, naming one field."""

    def __init__(self, field: PreferenceField, message: str) -> None:
        self.field = field
        super().__init__(message)


class PreferenceChainOutOfOrder(DomainError):
    """A resolution was offered a chain with an Area's preference ahead of an override.

    Its own type rather than a :class:`PreferenceError`, because it names no field of a
    preference: nothing a caller sent is wrong, the order it asked in is.
    """


@dataclass(frozen=True, slots=True)
class LocalTimeWindow:
    """A preferred stretch of the day, as wall time: no date, and no zone.

    ``05:30`` means 05:30 wherever the user is, resolved against the zone active on the date
    the window is read for. That resolution is the week assembler's; nothing here holds a date.

    **An end of ``00:00`` means the END of the day, and that is the only relaxation of the rule
    that a window runs forward.** ``time`` cannot spell 24:00 and a bound is a ``time``, so the
    day's last instant is spelled as its first, and every ORDERING comparison of two bounds reads
    :attr:`opens_at_minute` and :attr:`closes_at_minute` rather than the ``time`` values: ``00:00``
    compares as the day's first minute and means its last.

    A window itself still never wraps. A stretch a user authors across midnight becomes the two
    windows :func:`authored_windows` splits it into, so nothing downstream holds a pair of bounds
    that run backwards. A window whose start equals its end stays refused, and that one rule is
    stated over the ``time`` values rather than over the minute coordinate: read as minutes,
    ``00:00`` to ``00:00`` opens at the day's first minute and closes at its last, so it would pass
    the forward rule and name every hour of the day. Refusing it keeps a whole day inexpressible as
    one window, because "anytime" is said by declaring no preference at all.
    """

    start: LocalTime
    end: LocalTime

    @property
    def opens_at_minute(self) -> int:
        """Minutes from midnight at the start."""
        return _minutes_from_midnight(self.start)

    @property
    def closes_at_minute(self) -> int:
        """Minutes from midnight at the end, which is :data:`MINUTES_IN_A_DAY` at the day's end."""
        if self.end == END_OF_DAY:
            return MINUTES_IN_A_DAY
        return _minutes_from_midnight(self.end)

    def __post_init__(self) -> None:
        for bound in (self.start, self.end):
            if bound.tzinfo is not None:
                raise PreferenceError(
                    PreferenceField.WINDOWS,
                    f"a preferred window is wall time and names no zone, got "
                    f"{bound.isoformat()}. The zone comes from the date the window is resolved "
                    "for, so an offset offered here would describe a different hour on every "
                    "date it is read against",
                )
            if bound.second or bound.microsecond:
                raise PreferenceError(
                    PreferenceField.WINDOWS,
                    f"a preferred window is minute-resolution, got {bound.isoformat()}. Every "
                    "figure the placement arithmetic derives is a count of minutes",
                )
            # The side this module takes on an open product question: a wall time the USER
            # chose owes the grid, because a placement does and a window is where the user
            # asked for one. The rule rests on the PRD's own example being grid-aligned and on
            # one rule holding wherever a user authors a wall time; the narrow window below is
            # what makes it NECESSARY rather than what makes it sufficient. Tickets 1151 and
            # 1161 hold the question for the whole product from opposite sides; if it resolves
            # the other way, this call is the line that goes.
            if not is_wall_time_on_snap_grid(bound):
                raise PreferenceError(
                    PreferenceField.WINDOWS,
                    f"a preferred window's bounds land on a quarter hour, got "
                    f"{bound.isoformat()}. Every placement lands on the grid, so a bound off it "
                    f"names a time no block may start or end at, and a window narrower than a "
                    f"block would name no legal placement at all. Round it to the quarter hour "
                    f"the placement would take anyway",
                )
        if self.start == self.end or self.opens_at_minute >= self.closes_at_minute:
            raise PreferenceError(
                PreferenceField.WINDOWS,
                f"a preferred window runs forward, got {self.start.isoformat()} to "
                f"{self.end.isoformat()}. A window that ends where it starts names no stretch of "
                "the day, or at 00:00 the whole of it, and neither is a preferred time: no "
                "preference at all is how anytime is said. One whose end is earlier still names "
                "two stretches, which is what a stretch across midnight is split into before "
                "either becomes a window; only an end of 00:00 runs to the end of the day",
            )

    def __str__(self) -> str:
        """``05:30-07:00``, the form the read model renders a window in."""
        return f"{self.start.strftime('%H:%M')}-{self.end.strftime('%H:%M')}"


@dataclass(frozen=True, slots=True)
class PreferenceOwner:
    """The one thing a preference is attached to, and which kind of thing it is.

    Two fields rather than three nullable ones, because exactly one owner exists: a shape that
    could hold an Area and a Habit at once would need a rule saying it must not.
    """

    kind: PreferenceOwnerKind
    id: AreaId | HabitId | TaskId

    @property
    def is_an_area(self) -> bool:
        """Whether this owner is the root of a preference chain rather than an override."""
        return self.kind is PreferenceOwnerKind.AREA


@dataclass(frozen=True, slots=True)
class Preference:
    """When an owner's work should happen, and how much it costs to place it elsewhere.

    The identifier and the tenant are the stored row's rather than fields here, in the same way
    a ``Habit`` holds what its invariants read and not its title: nothing below is stated over
    an identifier, and the owner is what a resolution reports as the source.

    ``windows`` may be empty, and on an override that is a statement rather than an omission:
    it replaces its Area's windows with none, which is how one habit opts out of a preference
    the rest of its Area keeps.
    """

    owner: PreferenceOwner
    windows: tuple[LocalTimeWindow, ...]
    strength: PreferenceStrength
    # The ideal length of one session, and only ever an ideal: a task's minimum chunk stays a
    # hard constraint, so a split below this duration is placed and charged to the
    # fragmentation objective term rather than refused. Ticket 34 owns that term.
    preferred_duration_minutes: int | None
    # An Area's hard daily ceiling, in minutes. Null on every other owner, by the rule below.
    max_per_day_minutes: int | None

    def __post_init__(self) -> None:
        if len(self.windows) > MAX_WINDOWS:
            raise PreferenceError(
                PreferenceField.WINDOWS,
                f"a preference names at most {MAX_WINDOWS} preferred windows, got "
                f"{len(self.windows)}. Past that it discriminates between none of them, and no "
                "preference at all is how anytime is said",
            )
        # Canonical order, so the times of day a preference names are a set rather than a list
        # whose order a caller could change without changing the preference. It is also the
        # order the read model renders them in: earliest first.
        ordered = tuple(
            sorted(
                self.windows, key=lambda window: (window.opens_at_minute, window.closes_at_minute)
            )
        )
        for earlier, later in pairwise(ordered):
            if later.opens_at_minute < earlier.closes_at_minute:
                raise PreferenceError(
                    PreferenceField.WINDOWS,
                    f"two preferred windows overlap, {earlier} and {later}. Their union is one "
                    "window, so the pair states nothing the single window does not, and a list "
                    "of them would stop saying how many times of day are named",
                )
        object.__setattr__(self, "windows", ordered)

        if self.preferred_duration_minutes is not None and not (
            MIN_PREFERRED_DURATION_MINUTES
            <= self.preferred_duration_minutes
            <= MAX_PREFERRED_DURATION_MINUTES
        ):
            raise PreferenceError(
                PreferenceField.PREFERRED_DURATION,
                f"an ideal session runs {MIN_PREFERRED_DURATION_MINUTES} to "
                f"{MAX_PREFERRED_DURATION_MINUTES} minutes, got "
                f"{self.preferred_duration_minutes}",
            )
        if self.preferred_duration_minutes is not None and not is_a_snap_multiple(
            self.preferred_duration_minutes
        ):
            raise PreferenceError(
                PreferenceField.PREFERRED_DURATION,
                f"an ideal session is a whole number of {SNAP_MINUTES}-minute steps, got "
                f"{self.preferred_duration_minutes}. A block starts and ends on the grid, so a "
                "duration off it could not be met by any placement and the fragmentation cost "
                "would never reach zero",
            )

        if self.max_per_day_minutes is None:
            return
        if not self.owner.is_an_area:
            raise PreferenceError(
                PreferenceField.MAX_PER_DAY,
                f"a daily cap is an Area's and this preference belongs to a "
                f"{self.owner.kind.value}. The cap is a hard constraint reaching the solver "
                "through the Area's own budget, so an override that could carry one would be an "
                "override that could relax it",
            )
        if not MIN_MAX_PER_DAY_MINUTES <= self.max_per_day_minutes <= MAX_MAX_PER_DAY_MINUTES:
            raise PreferenceError(
                PreferenceField.MAX_PER_DAY,
                f"a daily cap runs {MIN_MAX_PER_DAY_MINUTES} to {MAX_MAX_PER_DAY_MINUTES} "
                f"minutes, got {self.max_per_day_minutes}. A cap admitting no block at all says "
                "never rather than at most, and never is a forbidden Area",
            )


def authored_windows(*, start: LocalTime, end: LocalTime) -> tuple[LocalTimeWindow, ...]:
    """The windows one authored stretch of the day names: two where it wraps midnight, else one.

    ``23:00`` to ``01:00`` is two windows, ``23:00`` to the end of the day and midnight to
    ``01:00``, and this is where that split happens. Carrying the stretch as one window whose end
    is earlier than its start would leave every reader of a bound pair answering wrongly rather
    than refusing: the canonical order, the overlap rule, and the length a pair names all read the
    two bounds directly, and none of them can see a wrap.

    A stretch whose end is already ``00:00`` runs to the end of the day and is therefore one
    window, so no split can produce an empty second half. Every other refusal a bound carries is
    :class:`LocalTimeWindow`'s, raised on whichever half holds the offending bound.
    """
    if end != END_OF_DAY and _minutes_from_midnight(start) > _minutes_from_midnight(end):
        return (
            LocalTimeWindow(start=start, end=END_OF_DAY),
            LocalTimeWindow(start=END_OF_DAY, end=end),
        )
    return (LocalTimeWindow(start=start, end=end),)


def captured_from_slot(
    *,
    owner: PreferenceOwner,
    windows: tuple[LocalTimeWindow, ...],
    preferred_duration_minutes: int | None = None,
) -> Preference:
    """A preference derived from where the user dropped a block, which is always soft.

    There is no strength parameter, and that absence is the rule rather than a default: a pin
    made by dragging a block is UI convenience, and recording it as a strong window would
    hand the learning layer a training label the user never stated. It carries no daily cap
    either, because a cap is authored rather than observed.
    """
    return Preference(
        owner=owner,
        windows=windows,
        strength=PreferenceStrength.SOFT,
        preferred_duration_minutes=preferred_duration_minutes,
        max_per_day_minutes=None,
    )


def preference_in_effect(*chain: Preference | None) -> Preference | None:
    """The one preference in effect, from a chain ordered most specific first.

    An override's own preference, or its Area's, or none: one of them entire, never two
    merged. A habit that declares windows and no ideal duration therefore has no ideal
    duration, whatever its Area declares, which is what makes an override a replacement.

    An Area's preference may only be the LAST link, because it is the root of every chain. A
    caller that passed it first would make every override inert, and every window the user
    authored on a habit would silently stop being read.
    """
    last = len(chain) - 1
    for position, candidate in enumerate(chain):
        if candidate is not None and candidate.owner.is_an_area and position != last:
            raise PreferenceChainOutOfOrder(
                f"an Area's preference is the root of a chain and this one is at position "
                f"{position} of {len(chain)}. Ahead of an override it would shadow it, and the "
                "windows the user set on the override would never be read"
            )
    return next((candidate for candidate in chain if candidate is not None), None)
