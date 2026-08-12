"""``maturity_corpus``: observations sized to sit either side of every gate.

Three corpora per parameter is one too many. What a gate test needs is a pair -- one observation
short of the threshold, and exactly at it -- because a gate is a comparison and the only interesting
inputs are the two values on either side of it. :func:`below_the_gate` and :func:`at_the_gate` are
that pair, built from the same shape so the ONLY difference between them is the count.

:func:`unfittable` is the third corpus and it is a different kind: not too small, but constructed so
that a fit over it would be meaningless. A gate that only counted samples would pass on every one of
them, which is why they are here rather than left to a test to invent.

**Sized from the thresholds rather than from literals.** Revising a threshold is a configuration
change by design, and a fixture holding "eleven" would silently stop straddling the gate the day the
gate moved.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final
from uuid import UUID

from syncr_learning.config import (
    CHURN_TOLERANCE,
    CONTEXT_SWITCH_COST,
    DURATION_MULTIPLIER,
    MIN_DISTINCT_HOURS,
    OBJECTIVE_TERMS,
    OBJECTIVE_WEIGHTS,
    SKIP_PROBABILITY,
    THRESHOLDS,
    TIME_OF_DAY_FITNESS,
    TimeBucket,
)
from syncr_learning.observations import (
    ChurnObservation,
    DurationObservation,
    Observations,
    RankExample,
    SkipObservation,
    SwitchObservation,
    TimeOfDayObservation,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

AREA: Final = UUID("11111111-1111-4111-8111-111111111111")
OTHER_AREA: Final = UUID("22222222-2222-4222-8222-222222222222")

# What a block is planned for and what it really takes, in the corpus below. The ratio is 82/60,
# which is the estimate error ``statements.py`` quotes in words.
PLANNED_MINUTES: Final = 60
ACTUAL_MINUTES: Final = 82

# How much more room the corpus leaves across an Area change than within one, before shrinkage.
SWITCH_GAP_MINUTES: Final = 45
SAME_AREA_GAP_MINUTES: Final = 15

# How many moves each rearrangement in the corpus showed, and how many the user let stand.
MOVES_SHOWN: Final = 9


def below_the_gate() -> Observations:
    """Every parameter one observation short of its threshold. Nothing may be applied from this."""
    return _sized(-1)


def at_the_gate() -> Observations:
    """Every parameter exactly at its threshold. Everything may be applied from this."""
    return _sized(0)


def unfittable() -> Observations:
    """Plenty of observations, and not one parameter a fit could honestly produce.

    Four shapes, one per way a count-only gate can be fooled:

    - the fitness curve's evidence is crowded into a single hour, so twenty-three hours of the curve
      would be the prior while the curve claimed to be fitted;
    - the switch corpus holds only cross-Area pairs, so the difference the price is measured as has
      no baseline and is undefined;
    - every rearrangement moved nothing, so the user was shown no rearrangement to absorb;
    - every ranking pair is degenerate, so the corpus states which placement the user chose and
      nothing about why.
    """
    return Observations(
        durations=(),
        time_of_day=tuple(
            TimeOfDayObservation(area_id=AREA, hour=7, went_well=True)
            for _ in range(THRESHOLDS[TIME_OF_DAY_FITNESS] * 2)
        ),
        skips=(),
        switches=tuple(
            SwitchObservation(gap_minutes=SWITCH_GAP_MINUTES, changed_area=True)
            for _ in range(THRESHOLDS[CONTEXT_SWITCH_COST] * 2)
        ),
        churn=tuple(
            ChurnObservation(moves=0, overridden=0) for _ in range(THRESHOLDS[CHURN_TOLERANCE] * 2)
        ),
        ranking=tuple(
            RankExample(difference=dict.fromkeys(OBJECTIVE_TERMS, 0.0))
            for _ in range(THRESHOLDS[OBJECTIVE_WEIGHTS] * 2)
        ),
    )


def _sized(offset: int) -> Observations:
    """One corpus with every parameter at its threshold plus ``offset`` observations."""
    return Observations(
        durations=tuple(
            DurationObservation(
                area_id=AREA, planned_minutes=PLANNED_MINUTES, actual_minutes=ACTUAL_MINUTES
            )
            for _ in range(THRESHOLDS[DURATION_MULTIPLIER] + offset)
        ),
        time_of_day=tuple(
            # Spread across the day, because the fitness gate reads the spread as well as the count.
            TimeOfDayObservation(area_id=AREA, hour=_spread_hour(index), went_well=index % 4 != 0)
            for index in range(THRESHOLDS[TIME_OF_DAY_FITNESS] + offset)
        ),
        skips=tuple(
            SkipObservation(area_id=AREA, bucket=TimeBucket.MORNING, was_refused=index % 3 == 0)
            for index in range(THRESHOLDS[SKIP_PROBABILITY] + offset)
        ),
        switches=(
            *(
                SwitchObservation(gap_minutes=SWITCH_GAP_MINUTES, changed_area=True)
                for _ in range(THRESHOLDS[CONTEXT_SWITCH_COST] + offset)
            ),
            # The baseline population. Sized independently of the gate, because the gate counts the
            # cross-Area pairs and this is what they are measured against.
            *(
                SwitchObservation(gap_minutes=SAME_AREA_GAP_MINUTES, changed_area=False)
                for _ in range(THRESHOLDS[CONTEXT_SWITCH_COST])
            ),
        ),
        churn=tuple(
            ChurnObservation(moves=MOVES_SHOWN, overridden=0)
            for _ in range(THRESHOLDS[CHURN_TOLERANCE] + offset)
        ),
        ranking=tuple(_a_pair(index) for index in range(THRESHOLDS[OBJECTIVE_WEIGHTS] + offset)),
    )


def _spread_hour(index: int) -> int:
    """An hour of the day, cycling over enough of them to satisfy the spread condition."""
    return index % (MIN_DISTINCT_HOURS + 2)


def _a_pair(index: int) -> RankExample:
    """One pairwise preference in which every term both helps and hurts across the corpus.

    A corpus in which one term only ever improves and the rest only ever worsen is ranked correctly
    only by a vector with negative weights, and the fit rejects those. Rotating which term the
    user's choice improves is what a real corpus looks like and what makes the fit identified in all
    seven directions.
    """
    terms = list(OBJECTIVE_TERMS)
    improves = terms[index % len(terms)]
    costs = terms[(index + 1) % len(terms)]
    difference: Mapping[str, float] = {
        **dict.fromkeys(OBJECTIVE_TERMS, 0.0),
        improves: -1.0 - (index % 3) * 0.1,
        costs: 0.3 + (index % 4) * 0.05,
    }
    return RankExample(difference=dict(difference))
