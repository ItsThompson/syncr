"""Why a week has no plan, in the two words the screen has an empty state for.

A read never triggers work, so a week the plan horizon maintainer has not reached has no plan, and
saying so is what makes the horizon a visible product concept rather than an invisible assumption.
The alternatives were a read that queues work, which makes navigating a mutation, and a fabricated
empty document, which asserts a plan that does not exist.

## The precedence is readiness first, and the reason is that the actions have to work

A tenant with no Areas cannot plan ANY week, inside the horizon or beyond it. Reporting such a week
as beyond the horizon would offer two actions that both fail: extending the horizon plans nothing
without Areas, and solving the week is refused naming the very input the screen did not mention. So
a missing minimum input is reported wherever the week is, and the horizon is reported for a week
that could be planned and has not been.

## One word covers two states, and the statement is what separates them

The vocabulary is closed at two members, and there are three states a week with no plan can be in:
the minimum inputs are missing, the week is past the horizon, or the week is inside the horizon and
the maintainer has not reached it yet. The third is a transient, at most one tick wide, and its
nearest member is ``outside_horizon``: the action it offers, solve this week now, is exactly the
right one. The statement says which of the two states it really is, and ``covers_this_week`` says
so as a flag a client can branch on, so nothing in the response claims the week is beyond a horizon
that holds it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final, Literal, Self

from syncr_api.horizon.config import MAINTAINER_INTERVAL
from syncr_api.horizon.weeks import horizon_dates, horizon_weeks

if TYPE_CHECKING:
    from datetime import date

    from syncr_api.plans.readiness import MissingInput, PlanReadiness
    from syncr_domain.weeks import IsoWeek

type EmptyReason = Literal["outside_horizon", "setup_incomplete"]
OUTSIDE_HORIZON: Final[EmptyReason] = "outside_horizon"
SETUP_INCOMPLETE: Final[EmptyReason] = "setup_incomplete"
EMPTY_REASONS: Final = (OUTSIDE_HORIZON, SETUP_INCOMPLETE)

# How long a week inside the horizon can wait for its plan, in the words the statement uses. Read
# from the cadence itself, so the sentence cannot promise a wait the maintainer does not keep.
_TICK_MINUTES: Final = int(MAINTAINER_INTERVAL / timedelta(minutes=1))


@dataclass(frozen=True, slots=True)
class Horizon:
    """The rolling window of local dates the projection covers, and the weeks it reaches.

    Built from the maintainer's own two functions rather than from a second reading of the bound,
    so the week this route calls beyond the horizon is exactly the week the maintainer skips.
    """

    days: int
    through: date
    weeks: tuple[IsoWeek, ...]

    @classmethod
    def of(cls, *, today: date, days: int) -> Self:
        """The horizon ``days`` long from ``today``, a LOCAL date in the tenant's home zone."""
        covered = horizon_dates(today=today, horizon_days=days)
        return cls(
            days=days,
            # The last date covered rather than the half-open bound, because this is the date the
            # screen states and a user reading it wants the last day their plan reaches.
            through=covered[-1],
            weeks=horizon_weeks(today=today, horizon_days=days),
        )

    def covers(self, iso_week: IsoWeek) -> bool:
        """Whether the maintainer keeps this week supplied with a plan."""
        return iso_week in self.weeks


@dataclass(frozen=True, slots=True)
class EmptyWeek:
    """Why one week holds no plan, and the facts the two actions on the screen need.

    ``covers_this_week`` is stored rather than re-derived by a reader, because the question was
    already asked to choose the word: a second reading of it is how the flag and the word would
    come to disagree about the same week.
    """

    reason: EmptyReason
    statement: str
    missing: tuple[MissingInput, ...]
    horizon: Horizon
    covers_this_week: bool


def empty_week(iso_week: IsoWeek, *, readiness: PlanReadiness, horizon: Horizon) -> EmptyWeek:
    """Why ``iso_week`` has no plan. Total: every week without one gets one of the two words."""
    covered = horizon.covers(iso_week)
    if not readiness.is_ready:
        return EmptyWeek(
            reason=SETUP_INCOMPLETE,
            statement=(
                f"{iso_week} has no plan, because syncr still needs {readiness.statement()}. "
                "Declare what is missing and this week is planned without you asking again."
            ),
            missing=readiness.missing,
            horizon=horizon,
            covers_this_week=covered,
        )
    if not covered:
        return EmptyWeek(
            reason=OUTSIDE_HORIZON,
            statement=(
                f"{iso_week} is beyond your {horizon.days}-day planning horizon, which reaches "
                f"{horizon.through}. Extend the horizon to bring it in, or solve this week now."
            ),
            missing=(),
            horizon=horizon,
            covers_this_week=covered,
        )
    return EmptyWeek(
        reason=OUTSIDE_HORIZON,
        statement=(
            f"{iso_week} is inside your {horizon.days}-day planning horizon and its plan has not "
            f"been produced yet. syncr plans it without you asking, within {_TICK_MINUTES} "
            "minutes, or solve this week now."
        ),
        missing=(),
        horizon=horizon,
        covers_this_week=covered,
    )
