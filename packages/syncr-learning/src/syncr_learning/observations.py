"""What a fitter consumes: five observation kinds, each a literal a test can write by hand.

Every fitter takes a list of one of these and returns a :class:`~syncr_learning.results.FitResult`.
Nothing here reads a clock, a database or a plan, so a fitter's whole behaviour is decidable from
values written in a test file, which is what section 20's learning-unit layer means by "nothing.
Fitters take observation lists".

Each observation is a MEASUREMENT, already reduced from the rows it came from: the extractor decides
which hour a placement fell in and whether the day was confirmed, and by the time a fitter sees an
observation those questions are answered. That split is what keeps the exclusion rules in one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_learning.config import HOURS_PER_DAY, ConfigError

if TYPE_CHECKING:
    from syncr_domain.identifiers import AreaId
    from syncr_learning.config import TimeBucket


@dataclass(frozen=True, slots=True, kw_only=True)
class DurationObservation:
    """One confirmed block that reported how long it really took.

    Only a ``partial`` outcome carries the figure, which is why section 11 names that state as the
    sole source of the duration signal: every other state says the block ran as planned or not at
    all, and neither is an estimate error.
    """

    area_id: AreaId
    planned_minutes: int
    actual_minutes: int

    def __post_init__(self) -> None:
        if self.planned_minutes <= 0:
            raise ConfigError(
                f"a block planned for {self.planned_minutes} minutes is not one an estimate could "
                "be wrong about: the ratio this observation exists for would divide by nothing"
            )
        if self.actual_minutes <= 0:
            raise ConfigError(
                f"a block that really took {self.actual_minutes} minutes is a skip, which has its "
                "own state and carries no estimate error at all"
            )

    @property
    def ratio(self) -> float:
        """What one stated minute really cost. Above one when the user underestimated."""
        return self.actual_minutes / self.planned_minutes


@dataclass(frozen=True, slots=True, kw_only=True)
class TimeOfDayObservation:
    """One confirmed block, at the hour of the user's day it really happened in.

    ``went_well`` is the content being done rather than refused. A ``moved`` outcome went well at
    the hour it moved TO, which is why the extractor reads the actual interval for the hour and the
    state for the verdict: the user did the work, at a different hour, and both halves are signal.
    """

    area_id: AreaId
    hour: int
    went_well: bool

    def __post_init__(self) -> None:
        if not 0 <= self.hour < HOURS_PER_DAY:
            raise ConfigError(
                f"{self.hour} is not an hour of a local day: a fitness curve holds one value per "
                f"hour, and a day has {HOURS_PER_DAY}"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class SkipObservation:
    """One confirmed block, in the part of the day it was PLANNED for, and whether it was refused.

    Planned rather than actual, deliberately. A skip probability answers "would the user refuse work
    put here", so the bucket is the one the solver would be choosing, and a ``moved`` outcome is a
    refusal of the bucket it was planned in even though the work happened elsewhere.
    """

    area_id: AreaId
    bucket: TimeBucket
    was_refused: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class SwitchObservation:
    """Two adjacent confirmed blocks, and the room the week left between them.

    ``changed_area`` is what makes the pair one population or the other. The fitted price is the
    difference between the gap this user leaves across an Area change and the gap they leave within
    one, which is a measurement rather than an assumption: with only one of the two populations
    present the difference is undefined, and the fitter says so instead of returning the prior as
    though it had measured it.
    """

    gap_minutes: int
    changed_area: bool

    def __post_init__(self) -> None:
        if self.gap_minutes < 0:
            raise ConfigError(
                f"a gap of {self.gap_minutes} minutes is not room the week left: adjacency is over "
                "blocks in span order, so the second cannot begin before the first ends"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class ChurnObservation:
    """One rearrangement the user was shown, and how much of it they let stand.

    ``moves`` counts the blocks a new revision put somewhere else; ``overridden`` counts how many of
    them the user pinned back or elsewhere before the next revision. What the user ABSORBED is the
    difference, and the tolerance is how many they absorb: a user who absorbs eight moves and
    objects to the ninth has a tolerance near eight.
    """

    moves: int
    overridden: int

    def __post_init__(self) -> None:
        if self.moves < 0 or self.overridden < 0:
            raise ConfigError(
                f"a rearrangement of {self.moves} moves with {self.overridden} overridden counts "
                "blocks, and neither count can be negative"
            )

    @property
    def absorbed(self) -> int:
        """The moves the user let stand. Clamped at zero: more overrides than moves is not negative.

        More overrides than moves happens for an ordinary reason. A user may pin a block the new
        revision left where it was, which is an override of nothing, so the two counts are over
        overlapping but not nested sets.
        """
        return max(self.moves - self.overridden, 0)


@dataclass(frozen=True, slots=True, kw_only=True)
class RankExample:
    """One pairwise preference, as the difference in the seven measurements between the two sides.

    ``difference[term]`` is the term's raw measurement of the placement the USER chose minus its
    measurement of the placement the SOLVER proposed. So a term the user's choice improves is
    negative, and a weight vector ranks the pair correctly when the weighted sum is below zero.

    Recorded at the edit rather than recomputed here, because the weight set that priced it is
    versioned and will have moved on: E2 is the rule and this is the value that carries it.
    """

    difference: dict[str, float]

    @property
    def is_degenerate(self) -> bool:
        """Whether the two sides measured identically, so the pair expresses no preference.

        A pin that keeps a block where it already is compares a plan with itself. Counted as a
        sample it would be a row the fit learned nothing from, which is how a gate comes to pass on
        a corpus with no signal in it.
        """
        return all(value == 0.0 for value in self.difference.values())


@dataclass(frozen=True, slots=True, kw_only=True)
class Observations:
    """Everything the five fitters and the weight fit read, after every exclusion has been applied.

    One value because the run hands the whole of it to the gate evaluation, and because a test that
    wants to prove an exclusion asserts on the counts here: a corpus of off-plan days produces an
    ``Observations`` whose every list is empty, which is a stronger statement than a fitted value
    happening to equal a prior.
    """

    durations: tuple[DurationObservation, ...]
    time_of_day: tuple[TimeOfDayObservation, ...]
    skips: tuple[SkipObservation, ...]
    switches: tuple[SwitchObservation, ...]
    churn: tuple[ChurnObservation, ...]
    ranking: tuple[RankExample, ...]

    def total(self) -> int:
        """How many observations of every kind this corpus produced."""
        return (
            len(self.durations)
            + len(self.time_of_day)
            + len(self.skips)
            + len(self.switches)
            + len(self.churn)
            + len(self.ranking)
        )
