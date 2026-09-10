"""Doubles for services that request a solve after changing backlog-wide inputs."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_domain.weeks import IsoWeek


class RecordingSolveRequests:
    """Records each explicit set of weeks a service requests."""

    def __init__(self) -> None:
        self.requested: list[frozenset[IsoWeek]] = []

    async def request(self, weeks: frozenset[IsoWeek]) -> tuple[IsoWeek, ...]:
        self.requested.append(weeks)
        return tuple(sorted(weeks))


class FixedProjectionHorizon:
    """Answers the fixed horizon a service test supplies."""

    def __init__(self, weeks: tuple[IsoWeek, ...]) -> None:
        self._weeks = weeks

    async def weeks_at(self, now: datetime) -> tuple[IsoWeek, ...]:
        return self._weeks
