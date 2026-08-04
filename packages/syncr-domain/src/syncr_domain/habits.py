"""The Habit: how often, for how long, what happens on a miss, and what it binds to.

A Habit answers *when and how often*. Its binding source answers *what exactly*, and one
field covers every pattern in the reference weeks:

```
fixed     ──── the same content every occurrence. No cursor exists
rotation ───── an ordered variant list plus a DERIVED cursor
queue ──────── cadence from the Habit, content from the task backlog
```

**Cadence lives here and nowhere else.** A template expresses no recurrence at all, because
weekly and monthly recurrence is already expressible as a cadence, and two homes for one
concept would need composition and override rules for no added expressiveness.

Two shapes are deliberately absent.

**No preferred time.** When a habit's work should happen is a ``Preference``, which an Area
declares and a Habit may override wholly. A field here would be a third statement of the
same thing and the solver would have to decide which one wins.

**No cursor.** The rotation cursor is a projection of the outcome log, derived by
:mod:`syncr_domain.cursor`. There is nothing here for it to drift from.

This shape holds what the two derivations and the invariants read. A habit's title and its
Area are the persisted row's, in the same way ``syncr_domain.budgets.AreaShare`` holds what
the budget arithmetic is stated over and not the Area's name.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final, assert_never

from syncr_domain.errors import DomainError
from syncr_domain.snap import SNAP_MINUTES, is_a_snap_multiple

if TYPE_CHECKING:
    from syncr_domain.identifiers import HabitId

# One an hour over a nominal 168-hour week. The bound rejects a count no week could hold
# rather than describing a real week: `syncr_domain.weeks` is where a week's real length
# comes from, and a transition week is 167, 169, or neither.
MAX_TIMES_PER_WEEK: Final = 168

# `~1d` is `Daily()` spelled a second way, and one meaning gets one spelling: the assembler
# would expand both identically, so the two would be indistinguishable downstream.
MIN_APPROX_DAYS: Final = 2
# A habit recurring less often than annually is not a habit. That is a Task with a deadline.
MAX_APPROX_DAYS: Final = 365

# A block shorter than one grid step cannot start and end on the grid.
MIN_DURATION_MINUTES: Final = SNAP_MINUTES
# An occurrence longer than a day cannot be placed inside one.
MAX_DURATION_MINUTES: Final = 24 * 60

# A rotation longer than this is a queue, and `queue` is the binding source for that.
MAX_VARIANTS: Final = 24
# A variant is read in a block label, which is as tight as an Area's name in a pie legend.
VARIANT_MAX_LENGTH: Final = 60

# `debt_cap_periods` of zero would forgive every miss and raise the habit on the first one,
# which is `escalate`. One meaning gets one spelling, so the floor is one period.
MIN_DEBT_CAP_PERIODS: Final = 1
# Fifty-two weekly periods. Past a year of outstanding debt the backlog is useless, which is
# the whole reason a cap exists.
MAX_DEBT_CAP_PERIODS: Final = 52
DEFAULT_DEBT_CAP_PERIODS: Final = 2


class HabitError(DomainError):
    """A Habit's invariants reject the given declaration."""


class CadenceKind(StrEnum):
    """Which of the three cadences a stored row holds. The persistence discriminator."""

    TIMES_PER_WEEK = "times_per_week"
    DAILY = "daily"
    EVERY_APPROX_DAYS = "every_approx_days"


class MissPolicy(StrEnum):
    """What a missed occurrence does. See :mod:`syncr_domain.debt`."""

    FORGIVE = "forgive"
    DEBT = "debt"
    ESCALATE = "escalate"


class BindingSource(StrEnum):
    """Where an occurrence's content comes from."""

    FIXED = "fixed"
    ROTATION = "rotation"
    QUEUE = "queue"


@dataclass(frozen=True, slots=True)
class TimesPerWeek:
    """``4 / wk``. Placement is free within the week."""

    count: int

    def __post_init__(self) -> None:
        if not 1 <= self.count <= MAX_TIMES_PER_WEEK:
            raise HabitError(
                f"{self.count} times a week is not a cadence: a count runs from 1 to "
                f"{MAX_TIMES_PER_WEEK}"
            )


@dataclass(frozen=True, slots=True)
class Daily:
    """Every day."""


@dataclass(frozen=True, slots=True)
class EveryApproxDays:
    """``~7d``. Laundry, groceries, washing sheets."""

    days: int

    def __post_init__(self) -> None:
        if self.days < MIN_APPROX_DAYS:
            raise HabitError(
                f"every ~{self.days} days is not a cadence: an interval of "
                f"{MIN_APPROX_DAYS - 1} day or less is Daily(), which is the one spelling "
                "of it"
            )
        if self.days > MAX_APPROX_DAYS:
            raise HabitError(
                f"every ~{self.days} days is not a cadence: an interval runs to "
                f"{MAX_APPROX_DAYS} days, and something rarer than that is a task with a "
                "deadline"
            )


type Cadence = TimesPerWeek | Daily | EveryApproxDays
"""The three cadences, and nothing else."""


@dataclass(frozen=True, slots=True)
class Duration:
    """How long one occurrence runs: a fixed span, or an elastic range.

    Fixed is ``min == max``, so there is no kind to store and no pair of shapes to keep in
    step. Both bounds land on the fifteen-minute grid, which is what makes every duration the
    solver may choose between them land on it too.
    """

    min_minutes: int
    max_minutes: int

    def __post_init__(self) -> None:
        for label, minutes in (("minimum", self.min_minutes), ("maximum", self.max_minutes)):
            if not MIN_DURATION_MINUTES <= minutes <= MAX_DURATION_MINUTES:
                raise HabitError(
                    f"a {label} duration of {minutes} minutes is not a duration: it runs "
                    f"from {MIN_DURATION_MINUTES} to {MAX_DURATION_MINUTES} minutes"
                )
            if not is_a_snap_multiple(minutes):
                raise HabitError(
                    f"a {label} duration of {minutes} minutes does not land on the "
                    f"{SNAP_MINUTES}-minute grid, so a block carrying it could not either"
                )
        if self.max_minutes < self.min_minutes:
            raise HabitError(
                f"a duration of {self.min_minutes} to {self.max_minutes} minutes runs "
                "backwards: an elastic duration needs its minimum at or below its maximum"
            )

    @classmethod
    def fixed(cls, minutes: int) -> Duration:
        """This span or nothing."""
        return cls(min_minutes=minutes, max_minutes=minutes)

    @classmethod
    def elastic(cls, *, min_minutes: int, max_minutes: int) -> Duration:
        """Anywhere in this range, as the solver finds room."""
        return cls(min_minutes=min_minutes, max_minutes=max_minutes)

    @property
    def is_fixed(self) -> bool:
        """Whether this duration offers the solver no room to move."""
        return self.min_minutes == self.max_minutes


@dataclass(frozen=True, slots=True)
class Habit:
    """One recurring intention, as the invariants and the two derivations read it.

    Constructing one applies X3 and X4, so a rotation without variants and a non-rotation
    with them are both unrepresentable rather than merely discouraged.
    """

    id: HabitId
    cadence: Cadence
    duration: Duration
    miss_policy: MissPolicy
    binding_source: BindingSource
    variants: tuple[str, ...] = ()
    debt_cap_periods: int = DEFAULT_DEBT_CAP_PERIODS

    def __post_init__(self) -> None:
        _require_variants_matching_the_source(self.binding_source, self.variants)
        if not MIN_DEBT_CAP_PERIODS <= self.debt_cap_periods <= MAX_DEBT_CAP_PERIODS:
            raise HabitError(
                f"a debt cap of {self.debt_cap_periods} cadence periods is not a cap: it "
                f"runs from {MIN_DEBT_CAP_PERIODS} to {MAX_DEBT_CAP_PERIODS}. A cap of zero "
                "would forgive every miss and raise the habit on the first, which is what "
                f"{MissPolicy.ESCALATE.value!r} already says"
            )

    @property
    def rotates(self) -> bool:
        """Whether this habit's content comes from an ordered variant list."""
        return self.binding_source is BindingSource.ROTATION


def occurrences_per_period(cadence: Cadence) -> int:
    """How many occurrences one cadence period holds.

    A period is the span the cadence repeats over: a week for ``TimesPerWeek``, a day for
    ``Daily``, and the stated interval for ``EveryApproxDays``. The two interval cadences
    hold exactly one occurrence per period by construction, which is what makes their debt
    cap read as "this many periods behind".
    """
    match cadence:
        case TimesPerWeek(count=count):
            return count
        case Daily():
            return 1
        case EveryApproxDays():
            return 1
        case _:  # pragma: no cover - unreachable while Cadence has three members
            assert_never(cadence)


def cadence_kind(cadence: Cadence) -> CadenceKind:
    """Which kind ``cadence`` is, for a row that stores the discriminator."""
    match cadence:
        case TimesPerWeek():
            return CadenceKind.TIMES_PER_WEEK
        case Daily():
            return CadenceKind.DAILY
        case EveryApproxDays():
            return CadenceKind.EVERY_APPROX_DAYS
        case _:  # pragma: no cover - unreachable while Cadence has three members
            assert_never(cadence)


def build_cadence(
    kind: CadenceKind, *, times_per_week: int | None, approx_days: int | None
) -> Cadence:
    """The cadence a stored row holds, or a rejection naming what the kind needs.

    The inverse of :func:`cadence_kind` plus the row's two nullable numbers. A pair that
    does not match the kind is refused here rather than read as the kind's default, so a
    row carrying both numbers cannot resolve to one of them silently.
    """
    match kind:
        case CadenceKind.TIMES_PER_WEEK:
            _require_absent(kind, approx_days=approx_days)
            return TimesPerWeek(_required(kind, "times_per_week", times_per_week))
        case CadenceKind.DAILY:
            _require_absent(kind, times_per_week=times_per_week, approx_days=approx_days)
            return Daily()
        case CadenceKind.EVERY_APPROX_DAYS:
            _require_absent(kind, times_per_week=times_per_week)
            return EveryApproxDays(_required(kind, "approx_days", approx_days))
        case _:  # pragma: no cover - unreachable while CadenceKind has three members
            assert_never(kind)


def _require_variants_matching_the_source(
    binding_source: BindingSource, variants: tuple[str, ...]
) -> None:
    """X3 and X4: a rotation needs variants, and nothing else may carry any."""
    if binding_source is BindingSource.ROTATION:
        if not variants:
            raise HabitError(
                f"a {binding_source.value!r} habit needs an ordered variant list: the "
                "cursor is an index into it, so an empty list leaves nothing to bind"
            )
        _require_readable_variants(variants)
        return
    if variants:
        raise HabitError(
            f"a {binding_source.value!r} habit carries no variants, and this one names "
            f"{len(variants)}. Only {BindingSource.ROTATION.value!r} rotates; "
            f"{BindingSource.FIXED.value!r} repeats one content and "
            f"{BindingSource.QUEUE.value!r} draws it from the backlog"
        )


def _require_readable_variants(variants: tuple[str, ...]) -> None:
    if len(variants) > MAX_VARIANTS:
        raise HabitError(
            f"{len(variants)} variants is more than a rotation holds, which is "
            f"{MAX_VARIANTS}. A longer list is a backlog, and "
            f"{BindingSource.QUEUE.value!r} is the binding source that draws from one"
        )
    for position, variant in enumerate(variants):
        if not variant.strip():
            raise HabitError(f"variant {position} carries no name, so it names no content")
        if len(variant) > VARIANT_MAX_LENGTH:
            raise HabitError(
                f"variant {position} is {len(variant)} characters, and a variant is read in "
                f"a block label, so it runs to {VARIANT_MAX_LENGTH}"
            )


def _require_absent(kind: CadenceKind, **absent: int | None) -> None:
    """Refuse a stored number the kind does not use.

    A row carrying both numbers is a row two kinds could be read out of, so it is refused
    rather than resolved to whichever one the discriminator happens to name.
    """
    named = sorted(name for name, value in absent.items() if value is not None)
    if named:
        raise HabitError(f"a {kind.value!r} cadence carries no {', '.join(named)}")


def _required(kind: CadenceKind, what: str, value: int | None) -> int:
    if value is None:
        raise HabitError(f"a {kind.value!r} cadence needs {what}, and this row carries none")
    return value
