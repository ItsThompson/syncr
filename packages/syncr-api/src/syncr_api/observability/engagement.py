"""The health canary: consecutive weeks the user actually used the product.

Not a success target. A scheduler the user stopped opening has failed regardless of the other three
metrics, so this is the one figure that says whether anyone is still there.

A week counts when BOTH halves hold: a weekly session ran, and five or more days were confirmed. One
without the other is not engagement. A session with nothing confirmed is planning nobody followed;
a confirmed week with no session is a week the plan was inherited rather than made.

**A week that is majority off-plan is SKIPPED, not counted as a failure.** The off-plan feature
exists so the user can stop for a week. Breaking the streak on it would make the one metric that
measures whether they still use the product punish the feature that lets them not. A skipped week is
neither an engaged week nor the end of a streak: the walk passes through it.

The walk stops at the first week that is neither engaged nor skipped, so its cost is the streak's
length rather than the lookback's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

# Days a week must hold confirmations for. Five of seven, so a fortnight of two missed evenings is
# still an engaged week and a week the user answered for twice is not.
CONFIRMED_DAYS_REQUIRED: Final = 5


@dataclass(frozen=True, slots=True, kw_only=True)
class WeekEngagement:
    """One week, as the streak reads it."""

    ran_a_session: bool
    confirmed_days: int
    majority_off_plan: bool

    @property
    def is_skipped(self) -> bool:
        """Whether the streak passes through this week without counting or ending it."""
        return self.majority_off_plan

    @property
    def is_engaged(self) -> bool:
        """Whether the user both planned the week and answered for most of it."""
        return self.ran_a_session and self.confirmed_days >= CONFIRMED_DAYS_REQUIRED


def streak_weeks(weeks: Iterable[WeekEngagement]) -> int:
    """How many consecutive weeks were engaged, reading ``weeks`` newest first.

    A skipped week is passed through: it adds nothing and ends nothing. Anything else that is not
    engaged ends the walk, because a streak with a gap in it is two streaks.
    """
    counted = 0
    for week in weeks:
        if week.is_skipped:
            continue
        if not week.is_engaged:
            return counted
        counted += 1
    return counted
