"""Fakes and builders for the outcome suite: a plan of record, an outcome log, and a bump.

Every fake here is the REAL repository's interface over a list of records and no database. The
domain is real throughout: the zone resolution, the interval algebra, the attribution table, the
plan document's own invariants and every value type are the shipped ones, because a stubbed
derivation would let this suite pass while a figure was wrong. The stored document is serialized
and rebuilt through the real ``stored_documents`` pair, so a fake plan is a plan the repository
could have handed back.

``FakeOutcomeLog`` is the one fake that reimplements behavior rather than storage: the
one-row-per-block identity, the presume-then-stamp order, and the keep-the-first-confirmation rule.
That is a real risk, so the same rules are driven against a real Postgres in
``test_outcomes_routes_integration.py``: what this suite buys is the service's decisions, and what
that one buys is that the statements do what this claims.

The week-scoped builders come from ``assembly_fakes`` rather than being spelled again: an Area, a
plan document, a settings row and a travel override are the same values here as there, and a
second home for any of them would be a second thing to keep in step. Ticket 1132 owns collapsing
the remaining duplication across suites.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from syncr_api.core.principal import Principal
from syncr_api.core.scopes import Scope
from syncr_api.outcomes.planned_days import PlannedDayReader
from syncr_api.outcomes.service import OutcomeService
from syncr_api.plans.config import APPLIED
from syncr_api.plans.reality import BlockOutcomeRepository
from syncr_api.plans.records import BlockOutcomeRecord, PlanRevisionRecord
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import plan_document, stored_document
from syncr_api.user_settings.solve_inputs import BacklogWideBump
from syncr_domain.outcomes import OutcomeState
from tests.assembly_fakes import (
    TENANT,
    FakeAreas,
    FakeOverrides,
    FakeSettings,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_api.areas.repository import AreaRepository
    from syncr_api.plans.reality import Presumption
    from syncr_api.user_settings.repository import SettingsRepository, TravelOverrideRepository
    from syncr_api.user_settings.solve_inputs import WeekRange
    from syncr_domain.identifiers import PlanRevisionId
    from syncr_domain.identity import BlockId
    from syncr_domain.intervals import Interval
    from syncr_domain.outcomes import RecordedOutcome
    from syncr_domain.plan import PlanDocument
    from syncr_domain.weeks import IsoWeek

# The user every service test acts as. Every scope, which is what a browser session carries.
OWNER = Principal(tenant_id=TENANT, user_id=uuid4(), scopes=frozenset(Scope))

REVISION_CREATED_AT = datetime(2026, 2, 9, 5, 0, tzinfo=UTC)


def a_revision(document: PlanDocument, *, input_version: int = 1) -> PlanRevisionRecord:
    """One stored revision holding ``document``, serialized as the repository stores it."""
    return PlanRevisionRecord(
        id=uuid4(),
        tenant_id=TENANT,
        iso_week=document.iso_week,
        status=APPLIED,
        reason="materialized",
        document=stored_document(document),
        objective_breakdown={},
        weight_set_version=1,
        input_version=input_version,
        supersedes_id=None,
        created_at=REVISION_CREATED_AT,
        approved_at=None,
    )


class FakePlans(PlanRepository):
    """The plans of record a tenant holds, answering the latest-per-week read."""

    def __init__(self, stored: Sequence[PlanRevisionRecord] = ()) -> None:
        self._stored = tuple(stored)
        self.weeks_read: list[IsoWeek] = []

    async def latest(self, iso_week: IsoWeek) -> PlanRevisionRecord | None:
        self.weeks_read.append(iso_week)
        found = [row for row in self._stored if row.iso_week == iso_week]
        return found[-1] if found else None


class FakeOutcomeLog(BlockOutcomeRepository):
    """The outcome log over a dictionary, with the write rules the repository holds.

    Keyed by block id, which is the identity the unique index enforces: a second recording of one
    block replaces the first rather than joining it.
    """

    def __init__(self, stored: Sequence[BlockOutcomeRecord] = ()) -> None:
        self._rows = {row.block_id: row for row in stored}
        self.spans_read: list[Interval] = []

    async def record(
        self,
        outcome: RecordedOutcome,
        *,
        block_id: BlockId,
        revision_id: PlanRevisionId,
        occurred_at: datetime,
    ) -> BlockOutcomeRecord:
        previous = self._rows.get(block_id)
        written = BlockOutcomeRecord(
            id=uuid4() if previous is None else previous.id,
            tenant_id=TENANT,
            block_id=block_id,
            binding=outcome.binding,
            revision_id=revision_id,
            state=outcome.state,
            actual_minutes=outcome.actual_minutes,
            actual_interval=outcome.actual_interval,
            occurred_at=occurred_at,
            # The column the write leaves exactly as it was: recording is not confirming.
            confirmed_at=None if previous is None else previous.confirmed_at,
        )
        self._rows[block_id] = written
        return written

    async def settle(self, presumptions: Sequence[Presumption], *, at: datetime) -> int:
        stamped = 0
        for one in presumptions:
            row = self._rows.get(one.block_id) or _presumed(one)
            if row.confirmed_at is None:
                self._rows[one.block_id] = replace(row, confirmed_at=at)
                stamped += 1
            else:
                self._rows[one.block_id] = row
        return stamped

    async def for_span(self, span: Interval) -> tuple[BlockOutcomeRecord, ...]:
        self.spans_read.append(span)
        return tuple(
            sorted(
                (row for row in self._rows.values() if span.start <= row.occurred_at < span.end),
                key=lambda row: (row.occurred_at, row.block_id),
            )
        )


@dataclass
class FakeVersions:
    """The week input version counter, recording what would have been bumped."""

    bumped: list[WeekRange]

    async def bump(self, weeks: WeekRange) -> None:
        self.bumped.append(weeks)


def _presumed(one: Presumption) -> BlockOutcomeRecord:
    return BlockOutcomeRecord(
        id=uuid4(),
        tenant_id=TENANT,
        block_id=one.block_id,
        binding=one.binding,
        revision_id=one.revision_id,
        state=OutcomeState.PRESUMED,
        actual_minutes=None,
        actual_interval=None,
        occurred_at=one.occurred_at,
        confirmed_at=None,
    )


@dataclass(frozen=True, slots=True)
class Wired:
    """The service under test and the three collaborators a test asserts against."""

    service: OutcomeService
    plans: FakePlans
    log: FakeOutcomeLog
    versions: FakeVersions


def a_service(
    *,
    plans: Sequence[PlanRevisionRecord] = (),
    outcomes: Sequence[BlockOutcomeRecord] = (),
    log: FakeOutcomeLog | None = None,
    areas: AreaRepository | None = None,
    settings: SettingsRepository | None = None,
    overrides: TravelOverrideRepository | None = None,
    now: datetime,
) -> Wired:
    """The outcome service over fakes, with the real bump and the real read model.

    ``log`` takes an existing one, so a test about time passing builds a second service over the
    rows the first wrote rather than reaching into the service's own clock.
    """
    stored_plans = FakePlans(plans)
    kept = log if log is not None else FakeOutcomeLog(outcomes)
    versions = FakeVersions(bumped=[])
    settings_repository = settings or FakeSettings()
    return Wired(
        service=OutcomeService(
            plans=stored_plans,
            days=PlannedDayReader(stored_plans),
            outcomes=kept,
            areas=areas or FakeAreas(),
            settings=settings_repository,
            overrides=overrides or FakeOverrides(),
            bump=BacklogWideBump(versions, settings_repository),
            clock=lambda: now,
        ),
        plans=stored_plans,
        log=kept,
        versions=versions,
    )


def rebuilt(revision: PlanRevisionRecord) -> PlanDocument:
    """The document a stored revision holds, for a test asserting on a block's derived id."""
    return plan_document(revision.document)
