"""Turning a credential into a principal. The one module that runs before one exists.

Every other service method in the application takes a principal as its first argument
and authorizes it. These two cannot, because they are what PRODUCES one: sign-in
resolves a password into a subject, and resolution turns a presented cookie into a
subject. Keeping them in a module that is not ``service.py`` is what lets the
authorization boundary test assert its rule over every service method with no
exemption list, since an exemption list is a place a later method can be quietly added
to.

Rejections are deliberately indistinguishable on the wire. A caller learns "sign in",
never whether the email exists, whether the password was wrong, whether the session
expired, or whether it was revoked. The log records which of those it was, because
that distinction is an operator's question rather than a caller's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.accounts.config import SESSION_ABSOLUTE_LIFETIME, SESSION_SLIDE_INTERVAL
from syncr_api.accounts.emails import normalize_email
from syncr_api.accounts.passwords import verify_password
from syncr_api.accounts.records import SessionRecord
from syncr_api.accounts.session_tokens import mint_session_token
from syncr_api.core.errors import Unauthorized
from syncr_api.core.principal import Principal
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.accounts.repository import SessionRepository, UserRepository
    from syncr_api.accounts.session_tokens import SessionToken, TokenDigest
    from syncr_api.core.clock import Clock

# What every rejection says, whatever it was.
REJECTION_DETAIL = "Sign in to continue."

_log = get_logger("syncr.accounts")


@dataclass(frozen=True, slots=True)
class EstablishedSession:
    """A newly minted session, and the token the cookie has to carry.

    The token appears here and nowhere else: it is not persisted, not logged, and not
    recoverable from the row, so this value object is the only path from minting it to
    setting the cookie.
    """

    token: SessionToken
    principal: Principal
    email: str
    expires_at: datetime


class Authenticator:
    """Sign-in and cookie resolution, for the browser credential."""

    def __init__(
        self,
        users: UserRepository,
        sessions: SessionRepository,
        digest: TokenDigest,
        clock: Clock,
    ) -> None:
        self._users = users
        self._sessions = sessions
        self._digest = digest
        self._clock = clock

    @measured("accounts")
    async def log_in(self, email: str, password: str) -> EstablishedSession:
        """Verify a password and establish a session. Raises 401 on any rejection."""
        user = await self._users.find_by_email(normalize_email(email))
        verified = verify_password(password, user.password_hash if user else None)
        if user is None or not verified:
            _log.warning(
                "accounts.sign_in.rejected",
                reason="no_such_user" if user is None else "wrong_password",
                user_id=str(user.id) if user else None,
            )
            raise Unauthorized(REJECTION_DETAIL)

        now = self._clock()
        token = mint_session_token()
        session = SessionRecord(
            id=self._digest(token),
            tenant_id=user.tenant_id,
            user_id=user.id,
            created_at=now,
            last_seen_at=now,
            expires_at=now + SESSION_ABSOLUTE_LIFETIME,
            revoked_at=None,
        )
        await self._sessions.create(session)
        _log.info(
            "accounts.sign_in.succeeded",
            tenant_id=str(user.tenant_id),
            user_id=str(user.id),
        )
        return EstablishedSession(
            token=token,
            principal=Principal(tenant_id=user.tenant_id, user_id=user.id),
            email=user.email,
            expires_at=session.usable_until(),
        )

    @measured("accounts")
    async def resolve(self, token: SessionToken) -> Principal:
        """The principal a presented cookie authenticates. Raises 401 otherwise.

        Slides the idle window as a side effect, which is what makes the session
        survive continued use. The write is throttled: a rewrite per request would put
        a write on the read path of every screen, and the idle window does not need
        second-level resolution.
        """
        session_id = self._digest(token)
        session = await self._sessions.find(session_id)
        now = self._clock()
        if session is None or not session.is_usable_at(now):
            _log.warning("accounts.session.rejected", reason=_rejection_reason(session, now))
            raise Unauthorized(REJECTION_DETAIL)

        if now - session.last_seen_at >= SESSION_SLIDE_INTERVAL:
            await self._sessions.touch(session_id, now)
        return Principal(tenant_id=session.tenant_id, user_id=session.user_id)


def _rejection_reason(session: SessionRecord | None, now: datetime) -> str:
    """Which rule rejected this session, for the log only."""
    if session is None:
        return "unknown_session"
    if session.revoked_at is not None:
        return "revoked"
    if now >= session.expires_at:
        return "past_absolute_cap"
    return "idle_too_long"
