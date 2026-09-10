from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from syncr_api.horizon.projection import CurrentProjectionHorizon
from syncr_domain.weeks import IsoWeek

NOW = datetime(2026, 2, 9, 0, 30, tzinfo=UTC)


@dataclass
class FakeTarget:
    horizon_days: int


@dataclass
class FakeSources:
    horizon_days: int

    async def write_target(self) -> FakeTarget:
        return FakeTarget(horizon_days=self.horizon_days)


@dataclass
class FakeSettings:
    home_zone: str

    async def read(self) -> FakeSettings:
        return self


async def test_the_current_projection_horizon_uses_a_home_zone_and_declared_length() -> None:
    horizon = CurrentProjectionHorizon(
        FakeSources(horizon_days=2), FakeSettings(home_zone="America/Los_Angeles")
    )

    weeks = await horizon.weeks_at(NOW)

    assert weeks == (IsoWeek(2026, 6), IsoWeek(2026, 7))
