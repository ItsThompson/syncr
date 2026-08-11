"""The calendar-source service's own decisions, with fakes at every boundary.

The route suite proves these reach the wire; the integration suite proves the schema backs them.
What is proven here is the service's own reasoning, which is where three things are decided:

**Which scope each method requires.** ``require_scope`` is the first act of every method, so a
credential too narrow for it is refused before anything is read. A reading method needs
``plan:read``; anything that changes a source needs ``admin``, because the write target and the
calendar catalogue are exactly what the admin scope is described as granting.

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
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.calendars.config import (
    ANCHOR_SOURCE,
    CALENDAR_PROVIDERS,
    EXCLUDED,
    GOOGLE,
    HORIZON_DAYS_DEFAULT,
    HORIZON_DAYS_MAX,
    ICS,
    NEVER_SYNCED,
    WRITE_TARGET,
)
from syncr_api.calendars.events import RemoteCalendar
from syncr_api.calendars.feed_notices import StaleFeedReading
from syncr_api.calendars.google_client import CalendarsAnswer, CalendarsRead, GoogleReadFailed
from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord
from syncr_api.calendars.service import CalendarSourceService, NewSource, SourceChange
from syncr_api.calendars.sync_state import recorded_failure
from syncr_api.core.errors import (
    Conflict,
    DependencyUnavailable,
    Forbidden,
    NotFound,
    ValidationFailed,
)
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import ALL_SCOPES, Scope
from syncr_api.solving.config import CALENDAR_SYNC, PENDING, SUCCEEDED
from syncr_api.solving.records import OperationRecord
from syncr_domain.intervals import Interval
from syncr_domain.zones import ZoneProfile
from tests.boundaries import public_methods

if TYPE_CHECKING:
    from syncr_api.calendars.config import CalendarProvider, CalendarRole
    from syncr_api.calendars.records import CalendarSourceId
    from syncr_api.user_settings.solve_inputs import WeekRange

NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)

LONDON = ZoneProfile(home_zone="Europe/London")
INGEST_HORIZON = Interval(NOW, NOW + timedelta(days=HORIZON_DAYS_DEFAULT))


class FakeAnchorStarts:
    """When a source's commitments begin. Empty for every source unless a test says otherwise."""

    def __init__(self) -> None:
        self.starts: dict[CalendarSourceId, tuple[datetime, ...]] = {}
        self.asked: list[CalendarSourceId] = []

    async def start_instants_for_source(
        self, source_id: CalendarSourceId, *, span: Interval
    ) -> tuple[datetime, ...]:
        self.asked.append(source_id)
        return tuple(at for at in self.starts.get(source_id, ()) if span.start <= at < span.end)


TIMETABLE = "https://example.ac.uk/timetable.ics"
REMOTE_CALENDAR = RemoteCalendar(
    calendar_id="primary",
    display_name="Personal",
    time_zone="Europe/London",
    writable=True,
    primary=True,
)
PLAN = "https://example.ac.uk/plan.ics"
GOOGLE_PLAN = "plan@group.calendar.google.com"

# The providers the plan cannot be written to, derived from the closed set rather than named, so a
# provider added to it is a decision the refusal below has to make. Held as a constant because an
# empty parameter list is a skip rather than a failure, and the test that asserts it is non-empty is
# what keeps the refusal from vanishing silently.
UNWRITABLE_PROVIDERS = tuple(one for one in CALENDAR_PROVIDERS if one != GOOGLE)

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
    # Listing an account's calendars is the calendar catalogue, which is what the admin scope is
    # described as granting, and it is reached only during setup.
    "list_remote_calendars": Scope.ADMIN,
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
        created_at=NOW,
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
    """Records which sources were synced, and answers with a completed operation.

    ``providers`` is what this deployment can read, and the service states its rule over it: a real
    syncer answers with the keys of the adapter map it was composed with, so a provider with no
    adapter is refused before a sync is attempted rather than fetched by the wrong one.
    """

    synced: list[CalendarSourceId] = field(default_factory=list)
    providers: frozenset[str] = field(default_factory=lambda: frozenset({ICS}))

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
class FakeRemoteCalendars:
    """The calendars an account holds, or the failure a read answers with.

    A fake over one method, because what the service decides is which rule applies and what a
    failure becomes on the wire: the reader itself is a provider boundary.
    """

    answer: CalendarsAnswer = field(
        default_factory=lambda: CalendarsRead(calendars=(REMOTE_CALENDAR,), attempts=1)
    )
    asked: int = 0

    async def list_calendars(self) -> CalendarsAnswer:
        self.asked += 1
        return self.answer


@dataclass
class Wiring:
    sources: FakeSources
    syncer: FakeSyncer
    versions: RecordingVersions
    remote_calendars: FakeRemoteCalendars
    anchors: FakeAnchorStarts
    service: CalendarSourceService


@pytest.fixture
def wiring() -> Wiring:
    sources = FakeSources()
    syncer = FakeSyncer()
    versions = RecordingVersions()
    remote_calendars = FakeRemoteCalendars()
    anchors = FakeAnchorStarts()
    return Wiring(
        sources=sources,
        syncer=syncer,
        versions=versions,
        remote_calendars=remote_calendars,
        anchors=anchors,
        service=CalendarSourceService(
            sources=sources,  # type: ignore[arg-type]  # a fake over the repository's surface
            syncer=syncer,  # type: ignore[arg-type]
            versions=versions,
            clock=lambda: NOW,
            remote_calendars=remote_calendars,
            # The real composer over a fake anchor read, so the listing this service answers with
            # is composed by the code that ships rather than by a stub that always says nothing.
            feeds=StaleFeedReading(anchors, profile=LONDON, horizon=INGEST_HORIZON),
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
        "list_remote_calendars": (uuid4(),),
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
        listing = await wiring.service.list_sources(READ_ONLY)
        assert (listing.sources, listing.notices) == ((), ())
        return
    with pytest.raises(NotFound):
        await wiring.service.read_source(READ_ONLY, uuid4())


async def test_another_tenants_source_is_not_found(wiring: Wiring) -> None:
    foreign = wiring.sources.hold(record(tenant_id=uuid4()))

    with pytest.raises(NotFound):
        await wiring.service.read_source(OWNER, foreign.id)


# --------------------------------------------------------------------------------
# The notices the listing carries
# --------------------------------------------------------------------------------


async def test_the_listing_carries_the_panel_a_stale_feed_raises(wiring: Wiring) -> None:
    # The rows and the notices come back from one call, decided against one instant. Two calls could
    # be given two clocks and then the table and its panel would disagree about the same feed.
    stale = wiring.sources.hold(
        record(sync_state=recorded_failure(SyncStateRecord(), at=NOW, reason="No answer."))
    )
    wiring.anchors.starts[stale.id] = (NOW + timedelta(days=1),)

    listing = await wiring.service.list_sources(OWNER)

    assert [source.id for source in listing.sources] == [stale.id]
    scopes = [notice.scope for notice in listing.notices]
    assert [scope and scope.source_id for scope in scopes] == [str(stale.id)]
    assert [scope and scope.dates for scope in scopes] == [["2026-02-10"]]


async def test_a_listing_of_healthy_sources_carries_no_notice_and_reads_no_anchor(
    wiring: Wiring,
) -> None:
    healthy = SyncStateRecord(last_success_at=NOW, last_attempt_at=NOW)
    wiring.sources.hold(record(sync_state=healthy))

    listing = await wiring.service.list_sources(OWNER)

    assert listing.notices == ()
    assert wiring.anchors.asked == []


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


async def test_a_never_synced_google_source_becomes_the_write_target_with_the_default_horizon(
    wiring: Wiring,
) -> None:
    held = wiring.sources.hold(record(provider=GOOGLE, external_id="primary"))

    designated = await wiring.service.designate_write_target(OWNER, held.id)

    assert designated.role == WRITE_TARGET
    assert designated.horizon_days == HORIZON_DAYS_DEFAULT


@pytest.mark.parametrize("provider", UNWRITABLE_PROVIDERS)
async def test_a_source_syncr_cannot_write_to_is_refused_naming_the_provider(
    wiring: Wiring, provider: CalendarProvider
) -> None:
    # Parametrized over the closed provider set rather than over `ics` by name, so a provider added
    # to it is a decision this rule has to make rather than one it silently accepts.
    held = wiring.sources.hold(record(provider=provider, external_id=PLAN))

    with pytest.raises(ValidationFailed) as raised:
        await wiring.service.designate_write_target(OWNER, held.id)

    assert f"is a {provider} source" in raised.value.detail
    assert "no API to write through" in raised.value.detail
    # What still works, so the refusal leaves the user able to decide what to do next.
    assert "still contributes its anchors" in raised.value.detail
    assert wiring.sources.rows[held.id].role == ANCHOR_SOURCE
    assert wiring.sources.rows[held.id].horizon_days is None


def test_the_unwritable_providers_are_a_non_empty_set() -> None:
    # The control for the parametrized refusal above. An empty parameter list collects as a skip, so
    # a provider set that ever held Google alone would retire that test without failing anything.
    assert UNWRITABLE_PROVIDERS
    assert GOOGLE not in UNWRITABLE_PROVIDERS


async def test_a_feed_is_refused_on_its_provider_even_when_another_source_holds_the_role(
    wiring: Wiring,
) -> None:
    # Two rules hold at once here, and only one of their remedies works: removing the other source's
    # role would leave this one still unwritable, so the provider refusal is the answer and the rule
    # that states it is applied first.
    wiring.sources.hold(
        record(
            provider=GOOGLE,
            external_id=GOOGLE_PLAN,
            role=WRITE_TARGET,
            horizon_days=14,
            display_name="syncr plan",
        )
    )
    feed = wiring.sources.hold(record(provider=ICS, external_id=PLAN))

    with pytest.raises(ValidationFailed) as raised:
        await wiring.service.designate_write_target(OWNER, feed.id)

    assert f"is a {ICS} source" in raised.value.detail
    assert wiring.sources.rows[feed.id].role == ANCHOR_SOURCE


async def test_a_feed_syncr_has_read_is_refused_on_its_provider_not_on_its_history(
    wiring: Wiring,
) -> None:
    # Both rules hold for this source, and the order between them decides which sentence the user
    # reads. The anchor-history remedy is to add a new empty calendar, which for a feed earns the
    # provider refusal on the second attempt, so the provider rule answers first.
    feed = wiring.sources.hold(
        record(
            provider=ICS,
            external_id=PLAN,
            sync_state=SyncStateRecord(last_success_at=NOW, anchors_current=61),
        )
    )

    with pytest.raises(ValidationFailed) as raised:
        await wiring.service.designate_write_target(OWNER, feed.id)

    assert f"is a {ICS} source" in raised.value.detail
    assert "active anchor source" not in raised.value.detail
    assert wiring.sources.rows[feed.id].role == ANCHOR_SOURCE


async def test_re_asserting_a_stored_unwritable_target_is_not_refused(wiring: Wiring) -> None:
    # The rule is stated over the transition. A role already stored is state no rule over a request
    # reaches, and refusing to re-assert it would answer 422 to a request that changes nothing;
    # the projection is what refuses to write such a target.
    held = wiring.sources.hold(
        record(provider=ICS, external_id=PLAN, role=WRITE_TARGET, horizon_days=21)
    )

    again = await wiring.service.designate_write_target(OWNER, held.id)

    assert again.role == WRITE_TARGET
    assert again.horizon_days == 21


async def test_a_source_that_has_ever_synced_cannot_become_the_write_target(
    wiring: Wiring,
) -> None:
    # "Active" is having ever synced, not currently reporting anchors: a feed that read zero
    # events last night is still a calendar the user reads elsewhere.
    held = wiring.sources.hold(
        record(
            provider=GOOGLE,
            external_id="read@example.org",
            sync_state=SyncStateRecord(last_success_at=NOW, anchors_current=0),
        )
    )

    with pytest.raises(ValidationFailed) as raised:
        await wiring.service.designate_write_target(OWNER, held.id)

    assert "reconciled destructively" in raised.value.detail
    assert wiring.sources.rows[held.id].role == ANCHOR_SOURCE


async def test_a_second_write_target_is_refused_naming_the_one_that_holds_the_role(
    wiring: Wiring,
) -> None:
    wiring.sources.hold(
        record(
            provider=GOOGLE,
            external_id=GOOGLE_PLAN,
            role=WRITE_TARGET,
            horizon_days=14,
            display_name="syncr plan",
        )
    )
    other = wiring.sources.hold(record(provider=GOOGLE, external_id="other@example.org"))

    with pytest.raises(Conflict) as raised:
        await wiring.service.designate_write_target(OWNER, other.id)

    assert "syncr plan" in raised.value.detail


async def test_re_designating_the_current_target_changes_nothing(wiring: Wiring) -> None:
    # PUT names a state, so re-asserting it must not be the 409 a SECOND target is.
    held = wiring.sources.hold(
        record(provider=GOOGLE, external_id="primary", role=WRITE_TARGET, horizon_days=21)
    )

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


async def test_a_forced_sync_on_a_provider_this_deployment_cannot_read_is_refused(
    wiring: Wiring,
) -> None:
    # The live case is a deployment with no Google credentials, which composes no Google adapter.
    # Without the guard the calendarId reaches whatever adapter is present, is fetched as a URL,
    # fails, and the source is recorded as failing with a transport message: the panel then says
    # the user's calendar is broken when the truth is that this deployment cannot read it.
    held = wiring.sources.hold(record(provider=GOOGLE, external_id="abc@group.calendar"))

    with pytest.raises(ValidationFailed) as raised:
        await wiring.service.sync_source(OWNER, held.id)

    assert "google" in raised.value.detail
    assert "nothing about this source is wrong" in raised.value.detail
    # Nothing was fetched and nothing was written, so the source does not read as failing.
    assert wiring.syncer.synced == []
    assert wiring.sources.rows[held.id].state == NEVER_SYNCED


async def test_a_forced_sync_on_a_google_source_is_allowed_where_google_is_readable(
    wiring: Wiring,
) -> None:
    # The other direction, and the reason the rule reads the adapter map rather than a constant: on
    # a deployment that CAN read Google, the same source syncs.
    wiring.syncer.providers = frozenset({ICS, GOOGLE})
    held = wiring.sources.hold(record(provider=GOOGLE, external_id="abc@group.calendar"))

    operation = await wiring.service.sync_source(OWNER, held.id)

    assert wiring.syncer.synced == [held.id]
    assert operation.status == SUCCEEDED


# --------------------------------------------------------------------------------
# The account's calendars, for selection during setup
# --------------------------------------------------------------------------------


async def test_the_remote_calendars_of_a_google_source_are_listed(wiring: Wiring) -> None:
    held = wiring.sources.hold(record(provider=GOOGLE, external_id="primary"))

    found = await wiring.service.list_remote_calendars(OWNER, held.id)

    assert found == (REMOTE_CALENDAR,)
    assert wiring.remote_calendars.asked == 1


async def test_listing_the_calendars_of_an_ics_source_is_refused_with_a_reason(
    wiring: Wiring,
) -> None:
    # A feed is one calendar at one address, so there is no list to choose from, and asking the
    # provider would be asking the wrong question rather than getting an empty answer.
    held = wiring.sources.hold(record())

    with pytest.raises(ValidationFailed, match="list of calendars"):
        await wiring.service.list_remote_calendars(OWNER, held.id)

    assert wiring.remote_calendars.asked == 0


async def test_a_failed_remote_read_is_a_dependency_failure_rather_than_an_empty_list(
    wiring: Wiring,
) -> None:
    # An empty list means "this account has no calendars", which would send the user looking for a
    # problem in Google's interface rather than reading what went wrong.
    wiring.remote_calendars.answer = GoogleReadFailed(reason="Google answered 503", attempts=4)
    held = wiring.sources.hold(record(provider=GOOGLE, external_id="primary"))

    with pytest.raises(DependencyUnavailable) as refused:
        await wiring.service.list_remote_calendars(OWNER, held.id)

    assert "Google answered 503" in refused.value.detail
    assert "still syncs" in refused.value.detail


async def test_removing_a_source_removes_it(wiring: Wiring) -> None:
    held = wiring.sources.hold(record())

    await wiring.service.remove_source(OWNER, held.id)

    assert wiring.sources.rows == {}


async def test_removing_another_tenants_source_removes_nothing(wiring: Wiring) -> None:
    foreign = wiring.sources.hold(record(tenant_id=uuid4()))

    with pytest.raises(NotFound):
        await wiring.service.remove_source(OWNER, foreign.id)

    assert foreign.id in wiring.sources.rows
