"""Builders for the learning suite: literals in, facts out.

Every fitter and the whole run are pure, so the suite's fixtures are values rather than a database.
These builders exist so a test states the ONE thing it is about -- a state, an hour, a confirmation
-- and inherits a coherent week for everything else.

Kept in one module because they build one corpus between them: a revision holds blocks, an outcome
names a block, and a test that seeds either without the other proves nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from syncr_domain.identity import BindingKind, BindingRef, block_id, index_occurrence_key
from syncr_domain.intervals import Interval
from syncr_domain.outcomes import OutcomeState
from syncr_domain.weeks import IsoWeek
from syncr_learning.facts import (
    HeldPin,
    LoggedOutcome,
    OffPlanSpan,
    PlannedBlock,
    RecordedEdit,
    StoredRevision,
    TenantCorpus,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_domain.identifiers import AreaId

ZONE = "Europe/London"
WEEK = IsoWeek(year=2026, week=7)
AREA = UUID("11111111-1111-4111-8111-111111111111")
OTHER_AREA = UUID("22222222-2222-4222-8222-222222222222")
TENANT = UUID("33333333-3333-4333-8333-333333333333")

# Monday of 2026-W07, in UTC. Every span in the suite is stated as an offset from this, so a test
# reads the hour it cares about rather than a full timestamp.
MONDAY = datetime(2026, 2, 9, tzinfo=UTC)


def at(*, day: int = 0, hour: int = 9, minute: int = 0) -> datetime:
    """An instant inside :data:`WEEK`, by weekday offset and local hour."""
    return MONDAY + timedelta(days=day, hours=hour, minutes=minute)


def span(*, day: int = 0, hour: int = 9, minutes: int = 60) -> Interval:
    """A block-shaped interval inside :data:`WEEK`."""
    start = at(day=day, hour=hour)
    return Interval(start, start + timedelta(minutes=minutes))


def binding(*, index: int = 0, kind: BindingKind = BindingKind.HABIT) -> BindingRef:
    """A distinct binding per ``index``, so two blocks of one week hold two block ids.

    The occurrence key is built through the domain's own padding rather than formatted here, because
    a key spelled any other way names a block that cannot exist and the pairing would match nothing.
    """
    return BindingRef(
        kind=kind,
        entity_id=UUID(int=index + 1),
        occurrence_key=index_occurrence_key(index),
        split_index=None,
    )


def planned(
    *,
    index: int = 0,
    area_id: AreaId | None = AREA,
    interval: Interval | None = None,
) -> PlannedBlock:
    """One block of a stored revision."""
    return PlannedBlock(
        binding=binding(index=index),
        interval=interval if interval is not None else span(),
        area_id=area_id,
    )


def revision(
    *,
    blocks: Sequence[PlannedBlock] = (),
    iso_week: IsoWeek = WEEK,
    created_at: datetime | None = None,
    zone_by_date: Mapping[object, str] | None = None,
) -> StoredRevision:
    """One stored revision of one week.

    ``zone_by_date`` defaults to every date of the week in :data:`ZONE`, which is what a real
    document captures: a test that wants a travelled week states its own.
    """
    return StoredRevision(
        iso_week=iso_week,
        created_at=created_at if created_at is not None else at(hour=0),
        zone_by_date=(
            dict(zone_by_date)  # type: ignore[arg-type]
            if zone_by_date is not None
            else dict.fromkeys(iso_week.dates(), ZONE)
        ),
        blocks=tuple(blocks),
    )


def outcome(
    *,
    index: int = 0,
    iso_week: IsoWeek = WEEK,
    state: OutcomeState = OutcomeState.COMPLETED,
    actual_minutes: int | None = None,
    actual: Interval | None = None,
    is_confirmed: bool = True,
) -> LoggedOutcome:
    """What the user said about the block ``index`` of ``iso_week``."""
    return LoggedOutcome(
        block_id=block_id(iso_week, binding(index=index)),
        state=state,
        actual_minutes=actual_minutes,
        actual=actual,
        is_confirmed=is_confirmed,
    )


def edit(
    *,
    iso_week: IsoWeek = WEEK,
    created_at: datetime | None = None,
    difference: Mapping[str, float] | None = None,
    objective_delta: float = 1.0,
    weight_set_version: int = 1,
    inside_off_plan: bool = False,
    accepted: Interval | None = None,
) -> RecordedEdit:
    """One pairwise preference. ``difference`` of ``None`` is a row predating the measurement."""
    return RecordedEdit(
        iso_week=iso_week,
        created_at=created_at if created_at is not None else at(hour=12),
        proposed=span(hour=6),
        accepted=accepted if accepted is not None else span(hour=13),
        objective_delta=objective_delta,
        measurement_delta=None if difference is None else dict(difference),
        weight_set_version=weight_set_version,
        inside_off_plan=inside_off_plan,
    )


def pin(
    *, index: int = 0, iso_week: IsoWeek | None = None, day: int = 1, hour: int = 13
) -> HeldPin:
    """One live pin of one week, at one local time."""
    week = iso_week if iso_week is not None else WEEK
    monday = datetime(week.monday().year, week.monday().month, week.monday().day, tzinfo=UTC)
    return HeldPin(
        binding=binding(index=index),
        iso_week=week,
        starts_at=monday + timedelta(days=day, hours=hour),
        zone=ZONE,
    )


def off_plan(*, day: int = 0, days: int = 1) -> OffPlanSpan:
    """One declared span of time off, from midnight of ``day`` for ``days``."""
    start = at(day=day, hour=0)
    return OffPlanSpan(interval=Interval(start, start + timedelta(days=days)))


def corpus(
    *,
    revisions: Sequence[StoredRevision] = (),
    outcomes: Sequence[LoggedOutcome] = (),
    edits: Sequence[RecordedEdit] = (),
    pins: Sequence[HeldPin] = (),
    spans: Sequence[OffPlanSpan] = (),
) -> TenantCorpus:
    """One tenant's whole corpus."""
    return TenantCorpus(
        tenant_id=TENANT,
        revisions=tuple(revisions),
        outcomes=tuple(outcomes),
        edits=tuple(edits),
        pins=tuple(pins),
        off_plan=tuple(spans),
    )


def a_week_of(
    count: int,
    *,
    state: OutcomeState = OutcomeState.PARTIAL,
    actual_minutes: int | None = 82,
    planned_minutes: int = 60,
    area_id: AreaId | None = AREA,
    hour: int = 9,
    is_confirmed: bool = True,
    iso_week: IsoWeek = WEEK,
) -> TenantCorpus:
    """A corpus of ``count`` blocks that all say the same thing. The size dial for the gate tests.

    Every block starts at a different minute of the same hour, so the hour is one and the block ids
    are ``count`` different values: a corpus of one repeated id would be one block however many rows
    it held.
    """
    blocks = [
        planned(
            index=index,
            area_id=area_id,
            interval=Interval(
                at(hour=hour, minute=index * 2),
                at(hour=hour, minute=index * 2) + timedelta(minutes=planned_minutes),
            ),
        )
        for index in range(count)
    ]
    outcomes = [
        outcome(
            index=index,
            iso_week=iso_week,
            state=state,
            actual_minutes=actual_minutes,
            is_confirmed=is_confirmed,
        )
        for index in range(count)
    ]
    return corpus(revisions=[revision(blocks=blocks, iso_week=iso_week)], outcomes=outcomes)


def uuid_key() -> str:
    """A fresh Area identifier as the string a stored map is keyed on."""
    return str(uuid4())
