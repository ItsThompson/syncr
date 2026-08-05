"""The minimum inputs a week needs before a plan can exist for it, and what is missing.

Two declarations, and a week without either cannot be planned rather than being planned badly.
**Areas**, because every discretionary block is charged to one and a plan with nothing to charge to
would allocate the week to no category at all. **A day shape**, because the week pattern is what
maps
each weekday to a template, and with no pattern nothing materializes: the frame would be the entire
plan.

Guessing at a plan without them would be worse than showing why one cannot exist. So the horizon
maintainer skips such a week and the Week screen states what is missing, which is the same answer
from two surfaces and is why the reading lives here rather than in either of them.

The reader is a small collaborator over two repositories rather than a function taking their rows,
because both callers hold a session and neither wants to know which tables the answer comes from: a
third declaration joining the minimum is a change here and nowhere else.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_api.areas.repository import AreaRepository
    from syncr_api.templates.repository import WeekPatternRepository


class MissingInput(StrEnum):
    """A declaration a week needs before it can be planned. Both, or the week is not planned."""

    AREAS = "areas"
    DAY_SHAPE = "day_shape"


# What each missing declaration is called where a person reads it, so the empty state names the
# thing the user has to go and create rather than the column it is stored in.
_NAMED: Final[Mapping[MissingInput, str]] = {
    MissingInput.AREAS: "at least one Area",
    MissingInput.DAY_SHAPE: "a day shape for each weekday",
}


@dataclass(frozen=True, slots=True)
class PlanReadiness:
    """Whether a week can be planned, and what is missing when it cannot.

    The missing list is ordered as the setup screen asks for them, Areas first, because a user
    reading it is being told what to do next and a day shape has nowhere to charge its slots until
    an Area exists.
    """

    missing: tuple[MissingInput, ...] = ()

    @property
    def is_ready(self) -> bool:
        """Whether every minimum input exists, so a plan may be produced."""
        return not self.missing

    def statement(self) -> str:
        """What is missing, in the words a person reads. Empty when nothing is."""
        return " and ".join(_NAMED[one] for one in self.missing)


class MinimumInputs:
    """Reads whether one tenant has declared what a plan needs."""

    def __init__(self, areas: AreaRepository, week_pattern: WeekPatternRepository) -> None:
        self._areas = areas
        self._week_pattern = week_pattern

    async def read(self) -> PlanReadiness:
        """Which minimum inputs this tenant is missing, in setup order. Writes nothing.

        A pattern maps all seven weekdays or it is not a pattern, so there is no partial mapping to
        interpret: the read is present or absent rather than counted.
        """
        missing: list[MissingInput] = []
        if not await self._areas.list_all():
            missing.append(MissingInput.AREAS)
        if await self._week_pattern.read() is None:
            missing.append(MissingInput.DAY_SHAPE)
        return PlanReadiness(tuple(missing))
