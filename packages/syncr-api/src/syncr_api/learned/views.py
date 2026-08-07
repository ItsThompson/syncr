"""The three shapes the learning routes answer with, before any wire concern touches them.

Kept separate from the schemas for the reason every other feature module keeps them separate: a view
is what the service computed and a schema is what a client receives, and the two diverge the first
time a field is renamed on the wire.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.learned.config import WeightSetOrigin
    from syncr_api.learned.maturity import ParameterMaturityReading


@dataclass(frozen=True, slots=True, kw_only=True)
class LearnedReading:
    """What the Learned screen renders: the parameters, their evidence, and the caveats.

    ``thresholds_are_estimates`` is served rather than left to the client's own copy. They ARE
    guesses and the screen says so; a caveat that lives only in a template is one a client can
    render without.

    ``unlocks_count_confirmed_volume`` is here for the same reason. A user has to understand that
    honesty is not penalised, or the whole dataset's integrity is at risk.
    """

    version: int
    origin: WeightSetOrigin
    fitted_at: datetime | None
    rows: tuple[ParameterMaturityReading, ...]
    ready: int
    collecting: int
    thresholds_are_estimates: str
    unlocks_count_confirmed_volume: str


@dataclass(frozen=True, slots=True, kw_only=True)
class WeightSetSummary:
    """One version, as the list renders it: which, from where, and whether it is in force."""

    version: int
    origin: WeightSetOrigin
    active: bool
    fitted_at: datetime | None
    created_at: datetime
    ready: int
    collecting: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ActivatedWeightSet:
    """What an activation answers with: the version now in force, and the weeks it re-solved.

    The week list is the answer to "what did this just change", and it is FUTURE weeks only: a past
    week's approved revision is immutable, so activating a version cannot move one.
    """

    version: int
    resolved_weeks: tuple[str, ...]
