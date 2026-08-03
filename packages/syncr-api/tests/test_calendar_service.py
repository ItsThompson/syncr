"""The calendar-source service's own decisions, with fakes at every boundary.

The route suite proves these reach the wire; the integration suite proves the schema backs them.
What is proven here is the service's own reasoning, which is where three things are decided:

**Which scope each method requires.** ``require_scope`` is the first act of every method, so a
credential too narrow for it is refused before anything is read. A reading method needs
``plan:read``; anything that changes a source needs ``admin``, because the write target and the
calendar catalogue are exactly what section 12 puts behind that scope.

**When the input version is bumped.** Changing the projection horizon changes what reaches the
phone, so the weeks the new range covers are invalidated. Nothing else here is a solve input:
renaming a source or excluding one changes no week's occupancy by itself, and a bump nobody
needs is a solve nobody asked for.

**What an excluded source reports.** Zero anchors, immediately, and an excluded state distinct
from an error, because the user's next question after excluding one is whether it stopped
counting.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.calendars.config import (
    ANCHOR_SOURCE,
    EXCLUDED,
    GOOGLE,
    HORIZON_DAYS_DEFAULT,
    HORIZON_DAYS_MAX,
    ICS,
    NEVER_SYNCED,
    WRITE_TARGET,
)
from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord
from syncr_api.calendars.service import CalendarSourceService, NewSource, SourceChange
from syncr_api.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import ALL_SCOPES, Scope
from syncr_api.solving.config import CALENDAR_SYNC, PENDING, SUCCEEDED
from syncr_api.solving.records import OperationRecord
from tests.boundaries import public_methods

if TYPE_CHECKING:
    from syncr_api.calendars.config import CalendarProvider, CalendarRole
    from syncr_api.calendars.records import CalendarSourceId
    from syncr_api.user_settings.solve_inputs import WeekRange

NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)

TIMETABLE = "https://example.ac.uk/timetable.ics"
PLAN = "https://example.ac.uk/plan.ics"

TENANT = uuid4()
OWNER = Principal(tenant_id=TENANT, user_id=uuid4(), scopes=ALL_SCOPES)
READ_ONLY = Principal(tenant_id=TENANT, user_id=uuid4(), scopes=frozenset({Scope.PLAN_READ}))

# Which scope each method demands. Stated as data so the parametrized test below covers every
# method and a method added without one fails the completeness check that follows it.
REQUIRED_SCOPES: dict[str, Scope] = {
    "list_sources": Scope.PLAN_READ,
    "read_source": Scope.PLAN_READ,
    "add_source": Scope.ADMIN,
    "change_source": Scope.ADMIN,
    "designate_write_target": Scope.ADMIN,
    "set_horizon": Scope.ADMIN,
    "sync_source": Scope.ADMIN,
    "remove_source": Scope.ADMIN,
}


def record(
    *,
    external_id: str = TIMETABLE,
    provider: CalendarProvider = ICS,
    role: CalendarRole = ANCHOR_SOURCE,
    included: bool = True,
    horizon_days: int | None = None,
    display_name: str = "University timetable",
    sync_state: SyncStateRecord | None = None,
    tenant_id: object = TENANT,
) -> CalendarSourceRecord:
    return CalendarSourceRecord(
        id=uuid4(),
        tenant_id=tenant_id,  # type: ignore[arg-type]  # a foreign tenant is a case under test
        provider=provider,
        role=role,
        display_name=display_name,
        external_id=external_id,
        included=included,
        horizon_days=horizon_days,
        sync_state=sync_state or SyncStateRecord(),
    )


@dataclass
class FakeSources:
    """The rows one tenant holds, keyed by identity, plus what was written to them."""

    rows: dict[CalendarSourceId, CalendarSourceRecord] = field(default_factory=dict)

    def hold(self, source: CalendarSourceRecord) -> CalendarSourceRecord:
        self.rows[source.id] = source
        return source

    async def list_all(self) -> tuple[CalendarSourceRecord, ...]:
        return tuple(self.rows.values())

    async def find(self, source_id: CalendarSourceId) -> CalendarSourceRecord | None:
        return self.rows.get(source_id)

    async def find_by_external_id(
        self, provider: CalendarProvider, external_id: str
    ) -> CalendarSourceRecord | None:
        return next(
            (
                row
                for row in self.rows.values()
                if row.provider == provider and row.external_id == external_id
            ),
            None,
        )

    async def write_target(self) -> CalendarSourceRecord | None:
        return next((row for row in self.rows.values() if row.role == WRITE_TARGET), None)

    async def create(
        self,
        *,
        provider: CalendarProvider,
        role: CalendarRole,
        display_name: str,
        external_id: str,
        included: bool,
        horizon_days: int | None,
        created_at: datetime,
    ) -> CalendarSourceRecord:
        return self.hold(
            record(
                provider=provider,
                role=role,
                display_name=display_name,
                external_id=external_id,
                included=included,
                horizon_days=horizon_days,
            )
        )

    async def set_inclusion(
        self, source_id: CalendarSourceId, *, included: bool, display_name: str | None
    ) -> None:
        held = self.rows[source_id]
        self.rows[source_id] = replace(
            held, included=included, display_name=display_name or held.display_name
        )

    async def set_horizon(self, source_id: CalendarSourceId, *, horizon_days: int) -> None:
        self.rows[source_id] = replace(self.rows[source_id], horizon_days=horizon_days)

    async def designate_write_target(
        self, source_id: CalendarSourceId, *, horizon_days: int
    ) -> None:
        self.rows[source_id] = replace(
            self.rows[source_id], role=WRITE_TARGET, horizon_days=horizon_days
        )

    async def remove(self, source_id: CalendarSourceId) -> None:
        del self.rows[source_id]


@dataclass
class FakeSyncer:
    """Records which sources were synced, and answers with a completed operation."""

    synced: list[CalendarSourceId] = field(default_factory=list)

    async def sync_now(self, source: CalendarSourceRecord) -> OperationRecord:
        self.synced.append(source.id)
        return OperationRecord(
            id=uuid4(),
            tenant_id=source.tenant_id,
            kind=CALENDAR_SYNC,
            status=SUCCEEDED,
            iso_week=None,
            source_id=source.id,
            input_version=None,
            candidate_adjustment=None,
            scheduled_for=NOW,
            started_at=NOW,
            finished_at=NOW,
            result_revision_id=None,
            superseded_by=None,
            attempt=1,
            error_code=None,
            error_message=None,
        )


@dataclass
class RecordingVersions:
    """Records what would have been bumped, rather than reaching plan storage."""

    bumped: list[WeekRange] = field(default_factory=list)

    async def bump(self, weeks: WeekRange) -> None:
        self.bumped.append(weeks)


@dataclass
class Wiring:
    sources: FakeSources
    syncer: FakeSyncer
    versions: RecordingVersions
    service: CalendarSourceService


@pytest.fixture
def wiring() -> Wiring:
    sources = FakeSources()
    syncer = FakeSyncer()
    versions = RecordingVersions()
    return Wiring(
        sources=sources,
        syncer=syncer,
        versions=versions,
        service=CalendarSourceService(
            sources=sources,  # type: ignore[arg-type]  # a fake over the repository's surface
            syncer=syncer,  # type: ignore[arg-type]
            versions=versions,
            clock=lambda: NOW,
        ),
    )


async def call(service: CalendarSourceService, name: str, principal: Principal) -> object:
    """One method, invoked with the least arguments it accepts, for the scope rules below."""
    arguments: dict[str, tuple[object, ...]] = {
        "list_sources": (),
        "read_source": (uuid4(),),
        "add_source": (NewSource(provider=ICS, display_name="Feed", external_id=TIMETABLE),),
        "change_source": (uuid4(), SourceChange(included=False)),
        "designate_write_target": (uuid4(),),
        "sync_source": (uuid4(),),
        "remove_source": (uuid4(),),
    }
    if name == "set_horizon":
        return await service.set_horizon(principal, uuid4(), horizon_days=HORIZON_DAYS_DEFAULT)
    method = getattr(service, name)
    return await method(principal, *arguments[name])


# --------------------------------------------------------------------------------
# Authorization
# --------------------------------------------------------------------------------


def test_every_public_method_has_a_stated_required_scope() -> None:
    # The completeness check for the table above: a method added without an entry would leave
    # its scope untested, and the parametrized test would still pass on the ones that have one.
    assert set(public_methods(CalendarSourceService)) == set(REQUIRED_SCOPES)


@pytest.mark.parametrize("name", sorted(REQUIRED_SCOPES))
async def test_a_credential_without_the_required_scope_is_refused(
    wiring: Wiring, name: str
) -> None:
    # Read-only carries plan:read only, so every admin method must refuse it. The two reading
    # methods are checked in the other direction below.
    if REQUIRED_SCOPES[name] == Scope.PLAN_READ:
        pytest.skip("checked by the reading test below")

    with pytest.raises(Forbidden):
        await call(wiring.service, name, READ_ONLY)


@pytest.mark.parametrize("name", ["list_sources", "read_source"])
async def test_a_reading_credential_reaches_the_reading_methods(wiring: Wiring, name: str) -> None:
    # The other half: a scope check that refused everything would pass the test above while
    # making the product unusable. A read with plan:read gets past the scope and reaches the
    # lookup, so the 404 below is the row missing rather than the scope.
    if name == "list_sources":
        assert await wiring.service.list_sources(READ_ONLY) == ()
        return
    with pytest.raises(NotFound):
        await wiring.service.read_source(READ_ONLY, uuid4())


async def test_another_tenants_source_is_not_found(wiring: Wiring) -> None:
    foreign = wiring.sources.hold(record(tenant_id=uuid4()))

    with pytest.raises(NotFound):
        await wiring.service.read_source(OWNER, foreign.id)


# --------------------------------------------------------------------------------
# Adding
# --------------------------------------------------------------------------------


async def test_an_ics_address_is_normalized_and_a_google_identifier_is_not(
    wiring: Wiring,
) -> None:
    feed = await wiring.service.add_source(
        OWNER, NewSource(provider=ICS, display_name=" Timetable ", external_id="webcal://x.ac.uk/t")
    )
    google = await wiring.service.add_source(
        OWNER,
        NewSource(provider=GOOGLE, display_name="Personal", external_id="abc@group.calendar"),
    )

    assert feed.external_id == "https://x.ac.uk/t"
    # The name is trimmed, because a panel row labelled with padding reads as a rendering bug.
    assert feed.display_name == "Timetable"
    assert feed.role == ANCHOR_SOURCE
    assert feed.horizon_days is None
    # A calendarId is the provider's own opaque identifier: rewriting it would break the read.
    assert google.external_id == "abc@group.calendar"


async def test_two_spellings_of_one_feed_collide(wiring: Wiring) -> None:
    await wiring.service.add_source(
        OWNER, NewSource(provider=ICS, display_name="Timetable", external_id=TIMETABLE)
    )

    with pytest.raises(Conflict):
        await wiring.service.add_source(
            OWNER,
            NewSource(
                provider=ICS,
                display_name="Again",
                external_id=TIMETABLE.replace("https://", "webcal://"),
            ),
        )


# --------------------------------------------------------------------------------
# Inclusion
# --------------------------------------------------------------------------------


async def test_excluding_a_source_reports_zero_anchors_and_an_excluded_state(
    wiring: Wiring,
) -> None:
    held = wiring.sources.hold(
        record(sync_state=SyncStateRecord(last_success_at=NOW, anchors_current=61))
    )

    changed = await wiring.service.change_source(OWNER, held.id, SourceChange(included=False))

    assert changed.state == EXCLUDED
    assert changed.anchor_count == 0
    # Nothing was deleted: the count the last sync established is still in the row.
    assert changed.sync_state.anchors_current == 61


async def test_a_rename_of_whitespace_leaves_the_name_alone(wiring: Wiring) -> None:
    # A panel row with no label would read as a rendering fault rather than as a rename.
    held = wiring.sources.hold(record(display_name="University timetable"))

    changed = await wiring.service.change_source(OWNER, held.id, SourceChange(display_name="   "))

    assert changed.display_name == "University timetable"


async def test_changing_a_source_bumps_no_input_version(wiring: Wiring) -> None:
    # Renaming or excluding a source changes no week's occupancy by itself, and a bump nobody
    # needs is a solve nobody asked for. The anchor reconciler bumps when anchors change.
    held = wiring.sources.hold(record())

    await wiring.service.change_source(OWNER, held.id, SourceChange(included=False))

    assert wiring.versions.bumped == []


# --------------------------------------------------------------------------------
# The role rules
# --------------------------------------------------------------------------------


async def test_a_never_synced_source_becomes_the_write_target_with_the_default_horizon(
    wiring: Wiring,
) -> None:
    held = wiring.sources.hold(record(external_id=PLAN))

    designated = await wiring.service.designate_write_target(OWNER, held.id)

    assert designated.role == WRITE_TARGET
    assert designated.horizon_days == HORIZON_DAYS_DEFAULT


async def test_a_source_that_has_ever_synced_cannot_become_the_write_target(
    wiring: Wiring,
) -> None:
    # "Active" is having ever synced, not currently reporting anchors: a feed that read zero
    # events last night is still a calendar the user reads elsewhere.
    held = wiring.sources.hold(
        record(sync_state=SyncStateRecord(last_success_at=NOW, anchors_current=0))
    )

    with pytest.raises(ValidationFailed) as raised:
        await wiring.service.designate_write_target(OWNER, held.id)

    assert "reconciled destructively" in raised.value.detail
    assert wiring.sources.rows[held.id].role == ANCHOR_SOURCE


async def test_a_second_write_target_is_refused_naming_the_one_that_holds_the_role(
    wiring: Wiring,
) -> None:
    wiring.sources.hold(
        record(external_id=PLAN, role=WRITE_TARGET, horizon_days=14, display_name="syncr plan")
    )
    other = wiring.sources.hold(record(external_id="https://x.ac.uk/other.ics"))

    with pytest.raises(Conflict) as raised:
        await wiring.service.designate_write_target(OWNER, other.id)

    assert "syncr plan" in raised.value.detail


async def test_re_designating_the_current_target_changes_nothing(wiring: Wiring) -> None:
    # PUT names a state, so re-asserting it must not be the 409 a SECOND target is.
    held = wiring.sources.hold(record(external_id=PLAN, role=WRITE_TARGET, horizon_days=21))

    again = await wiring.service.designate_write_target(OWNER, held.id)

    assert again.role == WRITE_TARGET
    assert again.horizon_days == 21


# --------------------------------------------------------------------------------
# The horizon
# --------------------------------------------------------------------------------


async def test_setting_the_horizon_bumps_the_weeks_the_new_range_covers(
    wiring: Wiring,
) -> None:
    held = wiring.sources.hold(record(external_id=PLAN, role=WRITE_TARGET, horizon_days=14))

    changed = await wiring.service.set_horizon(OWNER, held.id, horizon_days=28)

    assert changed.horizon_days == 28
    assert len(wiring.versions.bumped) == 1
    # From the current week onwards, to the week the far end of the horizon falls in.
    covered = wiring.versions.bumped[0]
    assert covered.last is not None
    assert covered.first <= covered.last


async def test_shortening_the_horizon_bumps_too(wiring: Wiring) -> None:
    # Both directions change what the projection writes. Re-solving a week that is still covered
    # costs one solve; missing one leaves the phone showing a plan the horizon no longer includes.
    held = wiring.sources.hold(record(external_id=PLAN, role=WRITE_TARGET, horizon_days=28))

    await wiring.service.set_horizon(OWNER, held.id, horizon_days=7)

    assert len(wiring.versions.bumped) == 1


async def test_a_horizon_on_an_anchor_source_is_refused(wiring: Wiring) -> None:
    held = wiring.sources.hold(record())

    with pytest.raises(ValidationFailed) as raised:
        await wiring.service.set_horizon(OWNER, held.id, horizon_days=21)

    assert "anchor source" in raised.value.detail
    assert wiring.versions.bumped == []


async def test_a_horizon_the_projection_cannot_use_is_refused(wiring: Wiring) -> None:
    # Restated in the service as well as in the request schema, because a caller reaching the
    # service without the HTTP boundary would otherwise get an IntegrityError from the CHECK.
    held = wiring.sources.hold(record(external_id=PLAN, role=WRITE_TARGET, horizon_days=14))

    with pytest.raises(ValidationFailed):
        await wiring.service.set_horizon(OWNER, held.id, horizon_days=HORIZON_DAYS_MAX + 1)

    assert wiring.sources.rows[held.id].horizon_days == 14


# --------------------------------------------------------------------------------
# Sync and removal
# --------------------------------------------------------------------------------


async def test_a_forced_sync_delegates_and_answers_with_a_terminal_operation(
    wiring: Wiring,
) -> None:
    held = wiring.sources.hold(record())

    operation = await wiring.service.sync_source(OWNER, held.id)

    assert wiring.syncer.synced == [held.id]
    assert operation.kind == CALENDAR_SYNC
    # Terminal, because a client follows this and a pending row nothing completes would never
    # resolve. The worker-loop ticket owns the general transition logic.
    assert operation.status == SUCCEEDED
    assert operation.status != PENDING


async def test_a_forced_sync_on_a_provider_syncr_does_not_read_is_refused(wiring: Wiring) -> None:
    # Without the guard the calendarId is handed to the ICS adapter as a URL, the fetch fails, and
    # the source is recorded as failing with a transport message: the panel then says the user's
    # calendar is broken when the truth is that syncr does not read Google yet.
    held = wiring.sources.hold(record(provider=GOOGLE, external_id="abc@group.calendar"))

    with pytest.raises(ValidationFailed) as raised:
        await wiring.service.sync_source(OWNER, held.id)

    assert "google" in raised.value.detail
    assert "nothing about this source is wrong" in raised.value.detail
    # Nothing was fetched and nothing was written, so the source does not read as failing.
    assert wiring.syncer.synced == []
    assert wiring.sources.rows[held.id].state == NEVER_SYNCED


async def test_removing_a_source_removes_it(wiring: Wiring) -> None:
    held = wiring.sources.hold(record())

    await wiring.service.remove_source(OWNER, held.id)

    assert wiring.sources.rows == {}


async def test_removing_another_tenants_source_removes_nothing(wiring: Wiring) -> None:
    foreign = wiring.sources.hold(record(tenant_id=uuid4()))

    with pytest.raises(NotFound):
        await wiring.service.remove_source(OWNER, foreign.id)

    assert foreign.id in wiring.sources.rows
