"""The sentence each maturity row states, in the words the user checks against their own experience.

The Learned screen is a trust surface rather than a diagnostic panel, and the plain-language line is
what builds that trust more than the number beside it. "You estimate 60m for Leetcode; your actual
median is 82m" is checkable against a memory; "duration_multiplier = 1.37" is not.

Every sentence here has to be true of a COLLECTING row as well as a ready one, because the screen
renders both, and "collecting" renders at informational volume: nothing is broken while a parameter
collects, and marking it as a warning would teach the user to distrust a working system.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syncr_learning.config import TimeBucket

_COLLECTING_SUFFIX = "Still collecting, which is normal."

UNMEASURED_EDITS_ARE_NEITHER_FITTED_NOR_COUNTED = (
    "An edit that carries no measured difference between the two placements cannot rank one "
    "against the other, so it is left out of the fit and does not count toward the threshold "
    "either."
)
"""Both halves, because the count the reader compares against the threshold is taken after the
exclusion.

Without the second half the two figures a reader meets disagree: a non-zero
``syncr_learning_edits_without_measurement`` beside a sample count that never moves is only
consistent under this rule. Stated with the row rather than in a client's own copy, so every surface
that draws the row draws the reason.
"""


def duration_statement(
    area_name: str,
    *,
    multiplier: float | None,
    planned_median: int | None,
    actual_median: int | None,
    samples: int,
    threshold: int,
) -> str:
    """What this Area's estimates are worth, quoted as the two medians rather than as the ratio."""
    if multiplier is None or planned_median is None or actual_median is None:
        return (
            f"{area_name}: {samples} of {threshold} blocks have reported how long they really "
            f"took. {_COLLECTING_SUFFIX}"
        )
    direction = "longer than" if actual_median > planned_median else "shorter than"
    return (
        f"You estimate {planned_median}m for {area_name}; your actual median is {actual_median}m, "
        f"which is {direction} planned, so estimates here are scaled by {multiplier:.2f}."
    )


def fitness_statement(
    area_name: str,
    *,
    best_hour: int | None,
    worst_hour: int | None,
    samples: int,
    threshold: int,
) -> str:
    """When this Area's work actually goes well, named as two hours of the user's own day."""
    if best_hour is None or worst_hour is None:
        return (
            f"{area_name}: {samples} of {threshold} confirmed blocks, spread across the day. "
            f"{_COLLECTING_SUFFIX}"
        )
    return (
        f"{area_name} goes best around {best_hour:02d}:00 and worst around {worst_hour:02d}:00, "
        "so the plan prefers the hours you actually finish this work in."
    )


def skip_statement(
    area_name: str,
    bucket: TimeBucket,
    *,
    probability: float | None,
    samples: int,
    threshold: int,
) -> str:
    """How often the user refuses this Area in this part of the day, as a share out of ten."""
    if probability is None:
        return (
            f"{area_name} in the {bucket.value}: {samples} of {threshold} confirmed blocks. "
            f"{_COLLECTING_SUFFIX}"
        )
    refused = round(probability * 10)
    return (
        f"You do not do {area_name} work in the {bucket.value} about {refused} times in 10, so the "
        "plan treats that part of your day as a poor fit for it."
    )


def switch_statement(*, minutes: float | None, samples: int, threshold: int) -> str:
    """What changing subject costs this user, in the minutes they really leave for it."""
    if minutes is None:
        return (
            f"Changing subject: {samples} of {threshold} adjacent pairs that cross an area, with "
            f"pairs inside one area to compare them against. {_COLLECTING_SUFFIX}"
        )
    return (
        f"You leave about {minutes:.0f} more minutes between blocks of different areas than "
        "between blocks of the same one, so the plan prices a change of subject at that."
    )


def churn_statement(*, moves: float | None, samples: int, threshold: int) -> str:
    """How much rearrangement this user absorbs before objecting."""
    if moves is None:
        return f"Rearrangement: {samples} of {threshold} proposals. {_COLLECTING_SUFFIX}"
    return (
        f"You let about {moves:.0f} moves stand before pinning one back, so the plan starts "
        "charging steeply for rearrangement past that."
    )


def weights_statement(
    *, samples: int, threshold: int, rejection: str | None, ranked: float | None
) -> str:
    """What the weights were fitted from, or why they were not, and what was left out of both.

    The exclusion is appended in every branch rather than only below the gate. A corpus whose rows
    all predate the measurement reaches the fit as no pairs at all, and no pairs is a REFUSAL rather
    than a collecting row, so the reader with the smallest sample count reads the refusal's words.
    """
    outcome = _weights_outcome(
        samples=samples, threshold=threshold, rejection=rejection, ranked=ranked
    )
    return f"{outcome} {UNMEASURED_EDITS_ARE_NEITHER_FITTED_NOR_COUNTED}"


def _weights_outcome(
    *, samples: int, threshold: int, rejection: str | None, ranked: float | None
) -> str:
    """The branch that says what happened to the vector: refitted, refused, or still collecting."""
    if ranked is not None:
        return (
            f"The seven weights were refitted from {samples} of your edits and now agree with "
            f"{ranked * 100:.0f}% of them, which is better than the weights they replace."
        )
    if rejection is not None:
        return f"The seven weights were not changed: {rejection}."
    return f"Your edits: {samples} of {threshold}. {_COLLECTING_SUFFIX}"
