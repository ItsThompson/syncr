"""The account service: what a connect states, what a callback accepts, and what expiry sounds like.

The token provider, the notice, and the service are one file because the interesting behaviour runs
through all three: a refresh fails, the failure is recorded with the instant it started, and the
notice built from that instant is the loudest non-blocking thing in the product.

Real everything except the two boundaries. The credential repository is a fake because a unit test
should not need Postgres, and the token endpoint is faked at the transport; the cipher, the state
parameter, the disclosure, the notice arithmetic, and the service's own ordering are all real.

Four claims are worth naming, because each is a rule rather than a mechanism:

- a transient failure does NOT start the expiry clock, so the loudest notice in the product cannot
  be raised by one 503 from Google;
- the instant the clock started does not move on a retry, so "failing for four days" stays true
  after the fourth day's poll;
- a reconnect clears the failure in the same act that stores the new grant, so the notice stops
  being raised by the repair rather than by a later poll;
- and a callback whose state names another tenant connects nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import httpx
import pytest

from syncr_api.calendars.config import ANCHOR_SOURCE, GOOGLE, ICS
from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord
from syncr_api.core.errors import DependencyUnavailable, Forbidden, ValidationFailed
from syncr_api.core.notices import BANNER, OXIDE, PANEL
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import ALL_SCOPES, Scope
from syncr_api.google_account.config import (
    ACCESS_TOKEN_SKEW,
    AUTHORIZATION_ENDPOINT,
    EVENTS_OWNED_SCOPE,
    REQUESTED_SCOPES,
)
from syncr_api.google_account.crypto import TokenCipher
from syncr_api.google_account.notices import (
    BANNER_NOTICE_ID,
    PANEL_NOTICE_ID,
    RECONNECT_LABEL,
    stated_duration,
    write_target_expiry_notices,
)
from syncr_api.google_account.oauth_client import GoogleOAuthClient
from syncr_api.google_account.outcomes import CONNECTED, DENIED, EXPIRED, FAILED
from syncr_api.google_account.records import GoogleCredentialRecord
from syncr_api.google_account.service import GoogleConnectionService
from syncr_api.google_account.state import issue_state
from syncr_api.google_account.tokens import (
    GoogleAccess,
    GoogleAccessTokens,
    GoogleGrantDead,
    GoogleUnreachable,
    NoGoogleAccount,
)
from tests.boundaries import public_methods
from tests.fake_google import (
    ACCESS_TOKEN,
    CLIENT_ID,
    CLIENT_SECRET,
    REDIRECT_URI,
    REFRESH_TOKEN,
    TEST_ENCRYPTION_KEY,
    token_answer,
    token_transport,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)
TENANT = uuid4()
OWNER = Principal(tenant_id=TENANT, user_id=uuid4(), scopes=ALL_SCOPES)
READ_ONLY = Principal(tenant_id=TENANT, user_id=uuid4(), scopes=frozenset({Scope.PLAN_READ}))
SIGNING_SECRET = "a-signing-secret-a-deployment-generated"  # pragma: allowlist secret

# Which scope each method demands, stated as data so the parametrized test covers every method and
# one added without an entry fails the completeness check that follows it.
REQUIRED_SCOPES: dict[str, Scope] = {
    "begin_connect": Scope.ADMIN,
    "complete_connect": Scope.ADMIN,
    "describe_connection": Scope.PLAN_READ,
}


@dataclass
class FakeCredentials:
    """The one row a tenant holds, and every write made to it."""

    row: GoogleCredentialRecord | None = None
    connects: int = 0

    async def read(self) -> GoogleCredentialRecord | None:
        return self.row

    async def connect(
        self, *, encrypted_refresh_token: str, granted_scopes: Sequence[str], at: datetime
    ) -> GoogleCredentialRecord:
        self.connects += 1
        self.row = GoogleCredentialRecord(
            id=uuid4(),
            tenant_id=TENANT,
            encrypted_refresh_token=encrypted_refresh_token,
            granted_scopes=tuple(granted_scopes),
            connected_at=at,
        )
        return self.row

    async def record_refresh(self, *, at: datetime) -> None:
        assert self.row is not None
        self.row = replace(
            self.row, last_refresh_at=at, refresh_failing_since=None, last_refresh_error=None
        )

    async def record_refresh_failure(self, *, at: datetime, reason: str) -> None:
        assert self.row is not None
        # The repository does this with COALESCE; the fake keeps the same rule, because a fake that
        # moved the instant would make the duration assertions pass for the wrong reason.
        self.row = replace(
            self.row,
            refresh_failing_since=self.row.refresh_failing_since or at,
            last_refresh_error=reason,
        )


@dataclass
class FakeSources:
    """The Google sources a tenant has configured, which the disclosure states."""

    rows: tuple[CalendarSourceRecord, ...] = ()

    async def list_for(self, provider: str) -> tuple[CalendarSourceRecord, ...]:
        return tuple(row for row in self.rows if row.provider == provider)


@dataclass
class Clock:
    """A clock a test moves, because every expiry claim here is clock arithmetic."""

    now: datetime = NOW

    def __call__(self) -> datetime:
        return self.now


def source(display_name: str = "Personal", *, included: bool = True) -> CalendarSourceRecord:
    return CalendarSourceRecord(
        id=uuid4(),
        tenant_id=TENANT,
        provider=GOOGLE,
        role=ANCHOR_SOURCE,
        display_name=display_name,
        external_id="primary",
        included=included,
        horizon_days=None,
        sync_state=SyncStateRecord(),
    )


def credential(**overrides: object) -> GoogleCredentialRecord:
    fields: dict[str, object] = {
        "id": uuid4(),
        "tenant_id": TENANT,
        "encrypted_refresh_token": TokenCipher(TEST_ENCRYPTION_KEY).encrypt(REFRESH_TOKEN),
        "granted_scopes": REQUESTED_SCOPES,
        "connected_at": NOW - timedelta(days=30),
    }
    return GoogleCredentialRecord(**{**fields, **overrides})  # type: ignore[arg-type]


def service(
    *,
    credentials: FakeCredentials | None = None,
    sources: FakeSources | None = None,
    handler: object = None,
    client_id: str = CLIENT_ID,
    clock: Clock | None = None,
) -> GoogleConnectionService:
    return GoogleConnectionService(
        credentials=credentials or FakeCredentials(),  # type: ignore[arg-type]
        sources=sources or FakeSources(),  # type: ignore[arg-type]
        oauth=GoogleOAuthClient(
            client=token_transport(handler or (lambda _request: token_answer())),
            client_id=client_id,
            client_secret=CLIENT_SECRET,
            redirect_uri=REDIRECT_URI,
        ),
        cipher=TokenCipher(TEST_ENCRYPTION_KEY),
        client_id=client_id,
        redirect_uri=REDIRECT_URI,
        state_secret=SIGNING_SECRET,
        clock=clock or Clock(),
    )


def tokens(
    *,
    credentials: FakeCredentials,
    handler: object = None,
    clock: Clock | None = None,
) -> GoogleAccessTokens:
    return GoogleAccessTokens(
        credentials=credentials,  # type: ignore[arg-type]
        oauth=GoogleOAuthClient(
            client=token_transport(handler or (lambda _request: token_answer())),
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            redirect_uri=REDIRECT_URI,
        ),
        cipher=TokenCipher(TEST_ENCRYPTION_KEY),
        clock=clock or Clock(),
    )


# --------------------------------------------------------------------------------------
# Authorization
# --------------------------------------------------------------------------------------


async def call(name: str, on: GoogleConnectionService, principal: Principal) -> object:
    """One service method, with the arguments that method takes."""
    if name == "complete_connect":
        return await on.complete_connect(principal, code="4/code", state=None, error=None)
    return await getattr(on, name)(principal)


@pytest.mark.parametrize("method", sorted(REQUIRED_SCOPES))
async def test_every_method_refuses_a_credential_too_narrow_for_it(method: str) -> None:
    required = REQUIRED_SCOPES[method]
    principal = Principal(
        tenant_id=TENANT, user_id=uuid4(), scopes=frozenset(ALL_SCOPES - {required})
    )

    with pytest.raises(Forbidden):
        await call(method, service(), principal)


def test_every_public_method_is_named_in_the_scope_table() -> None:
    # The control for the sweep above: a method added without an entry would leave the rule
    # passing vacuously.
    assert set(public_methods(GoogleConnectionService)) == set(REQUIRED_SCOPES)


# --------------------------------------------------------------------------------------
# The consent surface
# --------------------------------------------------------------------------------------


async def test_the_consent_surface_names_every_scope_in_plain_language() -> None:
    surface = await service().begin_connect(OWNER)

    assert tuple(disclosed.scope for disclosed in surface.scopes) == REQUESTED_SCOPES
    assert all(disclosed.statement for disclosed in surface.scopes)
    # The destructive one has to say so before consent, not after.
    written = next(one for one in surface.scopes if one.scope == EVENTS_OWNED_SCOPE)
    assert "destructively" in written.statement


async def test_the_authorization_url_asks_for_a_refresh_token_every_time() -> None:
    surface = await service().begin_connect(OWNER)

    assert surface.authorization_url.startswith(AUTHORIZATION_ENDPOINT)
    # Without offline access Google issues no refresh token at all, and without a forced consent it
    # issues none on a RECONNECT, which is the flow offered to repair a dead credential.
    assert "access_type=offline" in surface.authorization_url
    assert "prompt=consent" in surface.authorization_url


async def test_a_first_connect_states_that_nothing_is_read_until_it_is_included() -> None:
    surface = await service().begin_connect(OWNER)

    assert surface.calendars_read == ()
    assert "No calendar is read until you include it" in surface.statement


async def test_a_reconnect_names_the_calendars_that_will_be_read() -> None:
    sources = FakeSources(rows=(source("Personal"), source("Holidays", included=False)))

    surface = await service(sources=sources).begin_connect(OWNER)

    assert [(one.display_name, one.included) for one in surface.calendars_read] == [
        ("Personal", True),
        ("Holidays", False),
    ]
    assert "1 of the 2" in surface.statement


async def test_an_ics_source_is_not_named_on_a_google_consent_surface() -> None:
    feed = replace(source("University timetable"), provider=ICS)

    surface = await service(sources=FakeSources(rows=(feed,))).begin_connect(OWNER)

    assert surface.calendars_read == ()


async def test_a_deployment_with_no_client_refuses_and_names_what_still_works() -> None:
    with pytest.raises(DependencyUnavailable) as refused:
        await service(client_id="").begin_connect(OWNER)

    assert "GOOGLE_OAUTH_CLIENT_ID" in refused.value.detail
    assert "ICS feed still syncs" in refused.value.detail


# --------------------------------------------------------------------------------------
# The callback
# --------------------------------------------------------------------------------------


def state_for(tenant: UUID = TENANT, *, at: datetime = NOW) -> str:
    return issue_state(tenant_id=tenant, secret=SIGNING_SECRET, at=at)


async def test_a_completed_connect_stores_the_refresh_token_encrypted() -> None:
    credentials = FakeCredentials()

    outcome = await service(credentials=credentials).complete_connect(
        OWNER, code="4/code", state=state_for(), error=None
    )

    assert outcome == CONNECTED
    assert credentials.row is not None
    stored = credentials.row.encrypted_refresh_token
    assert REFRESH_TOKEN not in stored
    assert TokenCipher(TEST_ENCRYPTION_KEY).decrypt(stored) == REFRESH_TOKEN


async def test_a_reconnect_replaces_the_grant_and_clears_the_failure() -> None:
    failing = FakeCredentials(
        row=credential(refresh_failing_since=NOW - timedelta(days=4), last_refresh_error="dead")
    )

    await service(credentials=failing).complete_connect(
        OWNER, code="4/code", state=state_for(), error=None
    )

    assert failing.row is not None
    assert failing.row.refresh_failing_since is None
    assert failing.row.last_refresh_error is None


async def test_a_user_who_declined_is_not_a_failure() -> None:
    outcome = await service().complete_connect(
        OWNER, code=None, state=state_for(), error="access_denied"
    )

    assert outcome == DENIED


async def test_a_callback_with_no_code_and_no_error_connects_nothing() -> None:
    credentials = FakeCredentials()

    outcome = await service(credentials=credentials).complete_connect(
        OWNER, code=None, state=state_for(), error=None
    )

    assert outcome == FAILED
    assert credentials.connects == 0


@pytest.mark.parametrize(
    "state",
    [None, "forged", "v1.deadbeef.0.n.s"],
    ids=["absent", "forged", "plausible"],
)
async def test_a_callback_whose_state_does_not_verify_connects_nothing(state: str | None) -> None:
    credentials = FakeCredentials()

    outcome = await service(credentials=credentials).complete_connect(
        OWNER, code="4/code", state=state, error=None
    )

    assert outcome == EXPIRED
    assert credentials.connects == 0


async def test_a_state_issued_for_another_tenant_connects_nothing() -> None:
    # The whole reason the state carries a tenant: a code obtained in one account must not be
    # accepted into whoever is signed in now.
    credentials = FakeCredentials()

    outcome = await service(credentials=credentials).complete_connect(
        OWNER, code="4/code", state=state_for(uuid4()), error=None
    )

    assert outcome == EXPIRED
    assert credentials.connects == 0


async def test_an_answer_with_no_refresh_token_is_not_stored() -> None:
    # An access token alone produces an account that works for minutes and then dies silently, so
    # it is refused rather than half-connected.
    credentials = FakeCredentials()

    outcome = await service(
        credentials=credentials, handler=lambda _r: token_answer(refresh_token=None)
    ).complete_connect(OWNER, code="4/code", state=state_for(), error=None)

    assert outcome == FAILED
    assert credentials.connects == 0


async def test_a_token_endpoint_failure_connects_nothing() -> None:
    credentials = FakeCredentials()

    outcome = await service(
        credentials=credentials, handler=lambda _r: httpx.Response(503)
    ).complete_connect(OWNER, code="4/code", state=state_for(), error=None)

    assert outcome == FAILED
    assert credentials.connects == 0


async def test_a_refresh_token_too_wide_for_the_column_is_refused_before_the_write() -> None:
    oversize = "1//" + "x" * 4096
    credentials = FakeCredentials()

    with pytest.raises(ValidationFailed, match="still works"):
        await service(
            credentials=credentials, handler=lambda _r: token_answer(refresh_token=oversize)
        ).complete_connect(OWNER, code="4/code", state=state_for(), error=None)

    assert credentials.connects == 0


# --------------------------------------------------------------------------------------
# The access token, and what a dead grant does
# --------------------------------------------------------------------------------------


async def test_no_account_is_not_an_error_and_names_what_still_works() -> None:
    answer = await tokens(credentials=FakeCredentials()).current()

    assert isinstance(answer, NoGoogleAccount)
    assert "ICS feed still syncs" in answer.reason


async def test_a_refreshed_token_is_reused_within_its_lifetime() -> None:
    # One of these is built per sync pass, so five Google sources cost one refresh.
    refreshes = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal refreshes
        refreshes += 1
        return token_answer()

    source_of_tokens = tokens(credentials=FakeCredentials(row=credential()), handler=handler)

    first = await source_of_tokens.current()
    second = await source_of_tokens.current()

    assert isinstance(first, GoogleAccess)
    assert first.token == ACCESS_TOKEN
    assert second == first
    assert refreshes == 1


async def test_a_token_within_the_skew_of_expiry_is_refreshed_again() -> None:
    # A token used at the moment it expires fails in flight, and a sync pass holds one across
    # several calls.
    refreshes = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal refreshes
        refreshes += 1
        return token_answer(expires_in=int(ACCESS_TOKEN_SKEW.total_seconds()) + 10)

    clock = Clock()
    source_of_tokens = tokens(
        credentials=FakeCredentials(row=credential()), handler=handler, clock=clock
    )

    await source_of_tokens.current()
    clock.now += timedelta(seconds=20)
    await source_of_tokens.current()

    assert refreshes == 2


async def test_a_revoked_grant_records_when_writes_started_failing() -> None:
    credentials = FakeCredentials(row=credential())
    clock = Clock()

    answer = await tokens(
        credentials=credentials,
        handler=lambda _r: httpx.Response(400, json={"error": "invalid_grant"}),
        clock=clock,
    ).current()

    assert isinstance(answer, GoogleGrantDead)
    assert credentials.row is not None
    assert credentials.row.refresh_failing_since == clock.now


async def test_a_retry_does_not_move_the_instant_the_failing_started() -> None:
    # "Failing for four days" has to stay true after the fourth day's poll, which is why the
    # credential stores when it STARTED rather than when it last failed.
    credentials = FakeCredentials(row=credential())
    clock = Clock()
    dead = tokens(
        credentials=credentials,
        handler=lambda _r: httpx.Response(400, json={"error": "invalid_grant"}),
        clock=clock,
    )

    await dead.current()
    started = credentials.row.refresh_failing_since if credentials.row else None
    clock.now += timedelta(days=4)
    await tokens(
        credentials=credentials,
        handler=lambda _r: httpx.Response(400, json={"error": "invalid_grant"}),
        clock=clock,
    ).current()

    assert credentials.row is not None
    assert credentials.row.refresh_failing_since == started


async def test_google_being_unreachable_does_not_start_the_expiry_clock() -> None:
    # The loudest notice in the product must not be raised by one 503, or its operator learns to
    # ignore it.
    credentials = FakeCredentials(row=credential())

    answer = await tokens(credentials=credentials, handler=lambda _r: httpx.Response(503)).current()

    assert isinstance(answer, GoogleUnreachable)
    assert credentials.row is not None
    assert credentials.row.refresh_failing_since is None


async def test_a_ciphertext_this_deployment_cannot_read_is_a_dead_grant() -> None:
    credentials = FakeCredentials(row=credential(encrypted_refresh_token="not-ciphertext"))

    answer = await tokens(credentials=credentials).current()

    assert isinstance(answer, GoogleGrantDead)
    assert "granted again" in answer.reason


async def test_a_working_refresh_clears_a_previous_failure() -> None:
    credentials = FakeCredentials(
        row=credential(refresh_failing_since=NOW - timedelta(days=2), last_refresh_error="dead")
    )

    await tokens(credentials=credentials).current()

    assert credentials.row is not None
    assert credentials.row.refresh_failing_since is None
    assert credentials.row.last_refresh_at is not None


# --------------------------------------------------------------------------------------
# The notice
# --------------------------------------------------------------------------------------


def test_a_healthy_connection_raises_nothing() -> None:
    assert write_target_expiry_notices(credential(), now=NOW) == ()


def test_no_account_raises_nothing() -> None:
    # A tenant that never connected Google is not a tenant whose writes are failing.
    assert write_target_expiry_notices(None, now=NOW) == ()


def test_expiry_raises_a_banner_and_a_settings_panel() -> None:
    raised = write_target_expiry_notices(
        credential(refresh_failing_since=NOW - timedelta(days=4), last_refresh_error="revoked"),
        now=NOW,
    )

    assert [one.volume for one in raised] == [BANNER, PANEL]
    assert [one.id for one in raised] == [BANNER_NOTICE_ID, PANEL_NOTICE_ID]
    assert {one.pigment for one in raised} == {OXIDE}
    panel = raised[1]
    assert panel.scope is not None
    assert panel.scope.screen == "settings"


def test_the_notice_states_how_long_writes_have_been_failing() -> None:
    raised = write_target_expiry_notices(
        credential(refresh_failing_since=NOW - timedelta(days=4), last_refresh_error="revoked"),
        now=NOW,
    )

    assert "4 days" in raised[0].detail
    # The instant is carried as an instant, so it is serialized the way every other instant in the
    # document is rather than in a spelling of this module's own.
    assert raised[0].since == NOW - timedelta(days=4)


def test_the_notice_states_that_reading_works_and_writing_does_not() -> None:
    raised = write_target_expiry_notices(
        credential(refresh_failing_since=NOW - timedelta(hours=3), last_refresh_error="revoked"),
        now=NOW,
    )

    banner = raised[0]
    assert any("Reading" in capability for capability in banner.still_works)
    assert any("Writing" in capability for capability in banner.unavailable)
    assert banner.action is not None
    assert banner.action.label == RECONNECT_LABEL


def test_the_notice_offers_exactly_one_action() -> None:
    # A reader asked to choose between two repairs has been given a decision rather than a fix.
    raised = write_target_expiry_notices(
        credential(refresh_failing_since=NOW - timedelta(hours=3), last_refresh_error="x"), now=NOW
    )

    assert all(one.action is not None for one in raised)


@pytest.mark.parametrize(
    ("elapsed", "expected"),
    [
        (timedelta(seconds=5), "less than a minute"),
        (timedelta(minutes=1), "1 minute"),
        (timedelta(minutes=59), "59 minutes"),
        (timedelta(hours=1), "1 hour"),
        (timedelta(hours=23, minutes=59), "23 hours"),
        (timedelta(days=1), "1 day"),
        (timedelta(days=3, hours=20), "3 days"),
    ],
)
def test_a_duration_reads_as_a_number_a_person_would_say(elapsed: timedelta, expected: str) -> None:
    assert stated_duration(elapsed) == expected


def test_a_duration_rounds_down_rather_than_overstating() -> None:
    # The reader compares it against when they last saw the plan on their phone, so understating a
    # three-day-and-twenty-hour failure is safer than claiming four days.
    assert stated_duration(timedelta(days=3, hours=23, minutes=59)) == "3 days"


# --------------------------------------------------------------------------------------
# The read model
# --------------------------------------------------------------------------------------


async def test_the_connection_read_model_carries_the_notices_it_raises() -> None:
    credentials = FakeCredentials(
        row=credential(refresh_failing_since=NOW - timedelta(days=2), last_refresh_error="revoked")
    )

    connection = await service(credentials=credentials).describe_connection(READ_ONLY)

    assert connection.configured is True
    assert connection.connected is True
    assert len(connection.notices) == 2


async def test_an_unconfigured_deployment_says_so_rather_than_failing_the_read() -> None:
    # The read is how Settings decides what to render, so it answers even when a connect could not
    # be started.
    connection = await service(client_id="").describe_connection(READ_ONLY)

    assert connection.configured is False
    assert connection.connected is False
    assert connection.notices == ()
