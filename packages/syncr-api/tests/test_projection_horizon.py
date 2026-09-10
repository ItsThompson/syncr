from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from syncr_api.horizon.projection import CurrentProjectionHorizon
from syncr_domain.weeks import IsoWeek

NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)


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


async def test_the_current_projection_horizon_uses_the_tenants_local_date_and_length() -> None:
    horizon = CurrentProjectionHorizon(FakeSources(horizon_days=15), FakeSettings(home_zone="UTC"))

    weeks = await horizon.weeks_at(NOW)

    assert weeks == (IsoWeek(2026, 7), IsoWeek(2026, 8), IsoWeek(2026, 9))
