"""Sign-in, session resolution, and the authorization boundary, against fakes.

The repositories are replaced and the clock is injected, so the two lifetimes and the
sliding rule are tested by moving time rather than by waiting for it. Everything else is
real: the password derivation, the token minting, the keyed digest, and the expiry
arithmetic all run as they do in production, because those are the parts that would be
wrong silently.

The cross-tenant tests are the ones to read. They assert 404 and not 403, which is the
rule that keeps a session id from being confirmed as existing by the status code.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.accounts.authentication import Authenticator
from syncr_api.accounts.config import (
    SESSION_ABSOLUTE_LIFETIME,
    SESSION_IDLE_TIMEOUT,
    SESSION_SLIDE_INTERVAL,
)
from syncr_api.accounts.passwords import hash_password
from syncr_api.accounts.records import SessionRecord, UserRecord
from syncr_api.accounts.repository import SessionRepository, UserRepository
from syncr_api.accounts.service import SessionService
from syncr_api.accounts.session_tokens import make_token_digest
from syncr_api.core.errors import NotFound, Unauthorized
from syncr_api.core.principal import Principal

if TYPE_CHECKING:
    from syncr_api.accounts.session_tokens import SessionId
    from syncr_domain.identifiers import UserId

EMAIL = "owner@syncr.test"
PASSWORD = "correct-horse-battery-staple"  # pragma: allowlist secret
SIGNING_SECRET = "a-signing-secret-for-this-test"  # pragma: allowlist secret

START = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)


class MovableClock:
    """A clock a test advances, so an expiry is reached without waiting for it."""

    def __init__(self, at: datetime) -> None:
        self.now = at

    def __call__(self) -> datetime:
        return self.now

    def advance(self, by: timedelta) -> None:
        self.now += by


class FakeUserRepository(UserRepository):
    """The real repository's interface over a dict, with no database behind it."""

    def __init__(self, users: list[UserRecord]) -> None:
        self._by_email = {user.email: user for user in users}
        self._by_id = {user.id: user for user in users}

    async def find_by_email(self, email: str) -> UserRecord | None:
        return self._by_email.get(email)

    async def find(self, user_id: UserId) -> UserRecord | None:
        return self._by_id.get(user_id)


class FakeSessionRepository(SessionRepository):
    """Records what was written, so the service's effects are assertable."""

    def __init__(self) -> None:
        self.rows: dict[SessionId, SessionRecord] = {}

    async def find(self, session_id: SessionId) -> SessionRecord | None:
        return self.rows.get(session_id)

    async def create(self, record: SessionRecord) -> None:
        self.rows[record.id] = record

    async def touch(self, session_id: SessionId, at: datetime) -> None:
        self.rows[session_id] = _replaced(self.rows[session_id], last_seen_at=at)

    async def revoke(self, session_id: SessionId, at: datetime) -> None:
        existing = self.rows[session_id]
        if existing.revoked_at is None:
            self.rows[session_id] = _replaced(existing, revoked_at=at)


def _replaced(record: SessionRecord, **changes: datetime | None) -> SessionRecord:
    fields = {
        "id": record.id,
        "tenant_id": record.tenant_id,
        "user_id": record.user_id,
        "created_at": record.created_at,
        "last_seen_at": record.last_seen_at,
        "expires_at": record.expires_at,
        "revoked_at": record.revoked_at,
    }
    return SessionRecord(**{**fields, **changes})  # type: ignore[arg-type]


@pytest.fixture
def owner() -> UserRecord:
    return UserRecord(
        id=uuid4(), tenant_id=uuid4(), email=EMAIL, password_hash=hash_password(PASSWORD)
    )


@pytest.fixture
def clock() -> MovableClock:
    return MovableClock(START)


@pytest.fixture
def sessions() -> FakeSessionRepository:
    return FakeSessionRepository()


@pytest.fixture
def authenticator(
    owner: UserRecord, sessions: FakeSessionRepository, clock: MovableClock
) -> Authenticator:
    return Authenticator(
        users=FakeUserRepository([owner]),
        sessions=sessions,
        digest=make_token_digest(SIGNING_SECRET),
        clock=clock,
    )


@pytest.fixture
def service(
    owner: UserRecord, sessions: FakeSessionRepository, clock: MovableClock
) -> SessionService:
    return SessionService(sessions=sessions, users=FakeUserRepository([owner]), clock=clock)


# --- Signing in -----------------------------------------------------------------


async def test_signing_in_establishes_a_session_for_the_matching_user(
    authenticator: Authenticator, sessions: FakeSessionRepository, owner: UserRecord
) -> None:
    established = await authenticator.log_in(EMAIL, PASSWORD)

    assert established.principal == Principal(tenant_id=owner.tenant_id, user_id=owner.id)
    assert established.email == EMAIL
    assert len(sessions.rows) == 1


async def test_the_stored_row_holds_the_digest_and_never_the_token(
    authenticator: Authenticator, sessions: FakeSessionRepository
) -> None:
    established = await authenticator.log_in(EMAIL, PASSWORD)

    (stored,) = sessions.rows.values()
    assert stored.id == make_token_digest(SIGNING_SECRET)(established.token)
    assert established.token not in stored.id


async def test_the_cookie_expiry_is_the_idle_window_not_the_absolute_cap(
    authenticator: Authenticator,
) -> None:
    # The cookie has to outlive a browser restart but must not claim the whole cap: the
    # session dies at whichever rule bites first, and that is the idle window.
    established = await authenticator.log_in(EMAIL, PASSWORD)

    assert established.expires_at == START + SESSION_IDLE_TIMEOUT
    assert SESSION_IDLE_TIMEOUT < SESSION_ABSOLUTE_LIFETIME


async def test_the_stored_row_holds_the_absolute_cap(
    authenticator: Authenticator, sessions: FakeSessionRepository
) -> None:
    await authenticator.log_in(EMAIL, PASSWORD)

    (stored,) = sessions.rows.values()
    assert stored.expires_at == START + SESSION_ABSOLUTE_LIFETIME


async def test_a_wrong_password_is_rejected(authenticator: Authenticator) -> None:
    with pytest.raises(Unauthorized):
        await authenticator.log_in(EMAIL, "not the password")


async def test_an_unknown_email_is_rejected(authenticator: Authenticator) -> None:
    with pytest.raises(Unauthorized):
        await authenticator.log_in("nobody@syncr.test", PASSWORD)


async def test_a_rejection_says_the_same_thing_whichever_it_was(
    authenticator: Authenticator,
) -> None:
    # A caller must not be able to tell "no such account" from "wrong password", because
    # the difference answers whether an address has an account here.
    with pytest.raises(Unauthorized) as wrong_password:
        await authenticator.log_in(EMAIL, "not the password")
    with pytest.raises(Unauthorized) as unknown_email:
        await authenticator.log_in("nobody@syncr.test", PASSWORD)

    assert wrong_password.value.detail == unknown_email.value.detail


@pytest.mark.parametrize("presented", ["Owner@Syncr.TEST", "  owner@syncr.test  "])
async def test_the_email_is_normalized_before_it_is_matched(
    authenticator: Authenticator, presented: str
) -> None:
    established = await authenticator.log_in(presented, PASSWORD)

    assert established.email == EMAIL


async def test_nothing_is_stored_when_sign_in_fails(
    authenticator: Authenticator, sessions: FakeSessionRepository
) -> None:
    with pytest.raises(Unauthorized):
        await authenticator.log_in(EMAIL, "not the password")

    assert sessions.rows == {}


# --- Resolving a presented cookie -----------------------------------------------


async def test_a_fresh_session_resolves_to_its_principal(
    authenticator: Authenticator, owner: UserRecord
) -> None:
    established = await authenticator.log_in(EMAIL, PASSWORD)

    resolved = await authenticator.resolve(established.token)

    assert resolved == Principal(tenant_id=owner.tenant_id, user_id=owner.id)


async def test_an_unknown_token_is_rejected(authenticator: Authenticator) -> None:
    with pytest.raises(Unauthorized):
        await authenticator.resolve("syncrs_a-token-this-deployment-never-minted")


async def test_a_session_survives_a_gap_shorter_than_the_idle_window(
    authenticator: Authenticator, clock: MovableClock, owner: UserRecord
) -> None:
    established = await authenticator.log_in(EMAIL, PASSWORD)
    clock.advance(SESSION_IDLE_TIMEOUT - timedelta(minutes=1))

    assert await authenticator.resolve(established.token) == Principal(
        tenant_id=owner.tenant_id, user_id=owner.id
    )


async def test_a_session_unused_for_longer_than_the_idle_window_is_rejected(
    authenticator: Authenticator, clock: MovableClock
) -> None:
    established = await authenticator.log_in(EMAIL, PASSWORD)
    clock.advance(SESSION_IDLE_TIMEOUT + timedelta(seconds=1))

    with pytest.raises(Unauthorized):
        await authenticator.resolve(established.token)


async def test_using_a_session_slides_its_idle_window(
    authenticator: Authenticator, clock: MovableClock, sessions: FakeSessionRepository
) -> None:
    established = await authenticator.log_in(EMAIL, PASSWORD)

    # Used near the end of the window, then again a full window later: the second use
    # only works because the first one slid it.
    clock.advance(SESSION_IDLE_TIMEOUT - timedelta(hours=1))
    await authenticator.resolve(established.token)
    clock.advance(SESSION_IDLE_TIMEOUT - timedelta(hours=1))

    assert await authenticator.resolve(established.token) is not None
    (stored,) = sessions.rows.values()
    assert stored.last_seen_at == clock.now


async def test_sliding_never_moves_the_absolute_cap(
    authenticator: Authenticator, clock: MovableClock, sessions: FakeSessionRepository
) -> None:
    # The cap is what makes an abandoned-but-occasionally-used session eventually die,
    # so a use must not extend it. Six slides of nearly a full idle window fit inside the
    # cap; a seventh would not, which the next test asserts.
    established = await authenticator.log_in(EMAIL, PASSWORD)
    for _ in range(6):
        clock.advance(SESSION_IDLE_TIMEOUT - timedelta(hours=1))
        await authenticator.resolve(established.token)

    (stored,) = sessions.rows.values()
    assert stored.expires_at == START + SESSION_ABSOLUTE_LIFETIME
    assert clock.now < stored.expires_at


async def test_a_session_past_the_absolute_cap_is_rejected_however_often_it_is_used(
    authenticator: Authenticator, clock: MovableClock
) -> None:
    established = await authenticator.log_in(EMAIL, PASSWORD)
    # Used regularly right up to the cap, so the idle window can never be what refuses
    # it: only the cap can be.
    while clock.now < START + SESSION_ABSOLUTE_LIFETIME - SESSION_IDLE_TIMEOUT:
        clock.advance(SESSION_IDLE_TIMEOUT - timedelta(hours=1))
        await authenticator.resolve(established.token)
    clock.advance(SESSION_IDLE_TIMEOUT)

    with pytest.raises(Unauthorized):
        await authenticator.resolve(established.token)


async def test_the_slide_is_throttled_so_a_read_path_is_not_a_write_path(
    authenticator: Authenticator, clock: MovableClock, sessions: FakeSessionRepository
) -> None:
    established = await authenticator.log_in(EMAIL, PASSWORD)
    clock.advance(SESSION_SLIDE_INTERVAL / 2)
    await authenticator.resolve(established.token)

    (stored,) = sessions.rows.values()
    assert stored.last_seen_at == START, "a use inside the throttle window rewrote the row"


async def test_the_slide_happens_once_the_throttle_window_has_passed(
    authenticator: Authenticator, clock: MovableClock, sessions: FakeSessionRepository
) -> None:
    established = await authenticator.log_in(EMAIL, PASSWORD)
    clock.advance(SESSION_SLIDE_INTERVAL)
    await authenticator.resolve(established.token)

    (stored,) = sessions.rows.values()
    assert stored.last_seen_at == clock.now


# --- Reading and revoking, where authorization is enforced ----------------------


async def test_the_session_endpoint_describes_the_signed_in_principal(
    authenticator: Authenticator, service: SessionService, owner: UserRecord
) -> None:
    established = await authenticator.log_in(EMAIL, PASSWORD)
    session_id = make_token_digest(SIGNING_SECRET)(established.token)

    described = await service.describe(established.principal, session_id)

    assert described.tenant_id == owner.tenant_id
    assert described.user_id == owner.id
    assert described.email == EMAIL
    assert described.expires_at == START + SESSION_IDLE_TIMEOUT


async def test_signing_out_revokes_the_session_server_side(
    authenticator: Authenticator, service: SessionService, sessions: FakeSessionRepository
) -> None:
    established = await authenticator.log_in(EMAIL, PASSWORD)
    session_id = make_token_digest(SIGNING_SECRET)(established.token)

    await service.log_out(established.principal, session_id)

    (stored,) = sessions.rows.values()
    assert stored.revoked_at == START


async def test_a_revoked_session_no_longer_resolves(
    authenticator: Authenticator, service: SessionService
) -> None:
    # The cookie is unchanged and still presented: what stops it is the server's record.
    established = await authenticator.log_in(EMAIL, PASSWORD)
    session_id = make_token_digest(SIGNING_SECRET)(established.token)
    await service.log_out(established.principal, session_id)

    with pytest.raises(Unauthorized):
        await authenticator.resolve(established.token)


async def test_signing_out_twice_keeps_the_first_revocation_instant(
    authenticator: Authenticator,
    service: SessionService,
    sessions: FakeSessionRepository,
    clock: MovableClock,
) -> None:
    established = await authenticator.log_in(EMAIL, PASSWORD)
    session_id = make_token_digest(SIGNING_SECRET)(established.token)
    await service.log_out(established.principal, session_id)
    clock.advance(timedelta(hours=1))
    await service.log_out(established.principal, session_id)

    (stored,) = sessions.rows.values()
    assert stored.revoked_at == START


async def test_describing_another_tenants_session_is_a_404_and_never_a_403(
    authenticator: Authenticator, service: SessionService
) -> None:
    established = await authenticator.log_in(EMAIL, PASSWORD)
    session_id = make_token_digest(SIGNING_SECRET)(established.token)
    intruder = Principal(tenant_id=uuid4(), user_id=uuid4())

    with pytest.raises(NotFound) as rejected:
        await service.describe(intruder, session_id)

    assert rejected.value.status == 404


async def test_revoking_another_tenants_session_is_a_404_and_changes_nothing(
    authenticator: Authenticator, service: SessionService, sessions: FakeSessionRepository
) -> None:
    established = await authenticator.log_in(EMAIL, PASSWORD)
    session_id = make_token_digest(SIGNING_SECRET)(established.token)
    intruder = Principal(tenant_id=uuid4(), user_id=uuid4())

    with pytest.raises(NotFound):
        await service.log_out(intruder, session_id)

    (stored,) = sessions.rows.values()
    assert stored.revoked_at is None, "a foreign principal revoked someone else's session"


async def test_an_unknown_session_id_is_a_404(service: SessionService) -> None:
    with pytest.raises(NotFound):
        await service.describe(Principal(tenant_id=uuid4(), user_id=uuid4()), "0" * 64)


async def test_describing_a_revoked_session_is_a_404_even_with_its_own_principal(
    authenticator: Authenticator, service: SessionService
) -> None:
    # The service layer does not assume the caller already applied the expiry rule. Over
    # HTTP the principal dependency rejects this first; a later caller resolving a session
    # for another reason has no such guard.
    established = await authenticator.log_in(EMAIL, PASSWORD)
    session_id = make_token_digest(SIGNING_SECRET)(established.token)
    await service.log_out(established.principal, session_id)

    with pytest.raises(NotFound):
        await service.describe(established.principal, session_id)


async def test_describing_an_expired_session_is_a_404(
    authenticator: Authenticator, service: SessionService, clock: MovableClock
) -> None:
    established = await authenticator.log_in(EMAIL, PASSWORD)
    session_id = make_token_digest(SIGNING_SECRET)(established.token)
    clock.advance(SESSION_IDLE_TIMEOUT + timedelta(seconds=1))

    with pytest.raises(NotFound):
        await service.describe(established.principal, session_id)
