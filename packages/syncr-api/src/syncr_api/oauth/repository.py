"""Persistence for the Authorization Server.

Two repositories, split by WHEN the tenant is known, the same way accounts splits its own.

:class:`PresentedCredentialRepository` answers the questions that run before any tenant
exists: which client is this ``client_id``, and which row is this presented code or refresh
token. Every one of them is a primary-key read, because the row id IS the digest of the
secret the caller presented, so there is nothing to scan and no predicate to forget. What
protects a foreign row here is the service layer, which authorizes an explicit principal
against the row's own tenant.

:class:`OAuthRepository` is tenant-scoped and does everything after that: creating a code,
consuming one, upserting a grant, rotating a refresh token, revoking a family, and
sweeping expiries. It builds every statement from the scoped base, so the predicate is
applied once by the base rather than remembered by each method.

Two writes are deliberately expressed as guarded updates whose row count is the answer:
consuming a code and consuming a refresh token. A read-then-write would let two
simultaneous exchanges both see an unused row and both succeed, which is exactly the replay
single use exists to prevent. The database decides instead, and a row count of zero is what
tells the service it lost the race.

:class:`PresentedCredentialRepository` carries :func:`~syncr_api.core.db_metrics.measure_reads`
explicitly, because the hook that applies it to every scoped repository is on the base this one
cannot extend. What it times is the token endpoint: the authorization-code exchange and the
refresh-token exchange, which is where a presented credential is read. It is NOT the cost of an
authenticated request, because verifying a presented access token is arithmetic over a signed claim
set and reads no database at all.

No method commits. One request is one transaction, opened and committed by
:func:`syncr_api.core.db.get_transaction`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert as pg_insert

from syncr_api.core.db_metrics import measure_reads
from syncr_api.core.repository import TenantScopedRepository
from syncr_api.core.scopes import format_scopes
from syncr_api.core.tenancy import TENANT_ID_COLUMN
from syncr_api.oauth.models import (
    OAuthAuthorizationCode,
    OAuthClient,
    OAuthGrant,
    OAuthRefreshToken,
)
from syncr_api.oauth.records import (
    AuthorizationCodeRecord,
    ClientRecord,
    GrantRecord,
    RefreshTokenRecord,
    scopes_of,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_api.core.scopes import Scope


@measure_reads
class PresentedCredentialRepository:
    """Reads what the caller presented, before a tenant is known.

    Not tenant-scoped, and cannot be: the presented value is what supplies the scope. Every
    read is by primary key.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_client(self, client_id: str) -> ClientRecord | None:
        """The registered client with this id, or ``None``."""
        found = await self._session.get(OAuthClient, client_id)
        return _as_client(found) if found is not None else None

    async def find_code(self, code_id: str) -> AuthorizationCodeRecord | None:
        """The authorization code with this digest, or ``None``."""
        found = await self._session.get(OAuthAuthorizationCode, code_id)
        return _as_code(found) if found is not None else None

    async def find_refresh_token(self, token_id: str) -> RefreshTokenRecord | None:
        """The refresh token with this digest, or ``None``."""
        found = await self._session.get(OAuthRefreshToken, token_id)
        return _as_refresh_token(found) if found is not None else None

    async def find_grant(self, grant_id: UUID) -> GrantRecord | None:
        """The grant a presented refresh token belongs to, or ``None``.

        By primary key, and unscoped for the same reason as the reads above: the grant is
        reached from a presented token whose row supplied the tenant, and the service
        authorizes the two against each other rather than trusting either alone.
        """
        found = await self._session.get(OAuthGrant, grant_id)
        return _as_grant(found) if found is not None else None


class OAuthRepository(TenantScopedRepository):
    """One tenant's codes, grants, and refresh tokens, and no other tenant's.

    Row counts come from :meth:`~syncr_api.core.repository.TenantScopedRepository._affected_rows`,
    which is where the ``CursorResult`` cast that reads one lives.
    """

    async def create_code(
        self,
        *,
        code_id: str,
        client_id: str,
        redirect_uri: str,
        scopes: frozenset[Scope],
        code_challenge: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        """Persist a freshly minted authorization code."""
        self._session.add(
            OAuthAuthorizationCode(
                id=code_id,
                tenant_id=self.tenant_id,
                client_id=client_id,
                redirect_uri=redirect_uri,
                scope=format_scopes(scopes),
                code_challenge=code_challenge,
                created_at=created_at,
                expires_at=expires_at,
            )
        )
        await self._session.flush()

    async def consume_code(self, code_id: str, at: datetime) -> bool:
        """Mark a code used. ``False`` when it was already used, so a replay is visible.

        Guarded on ``consumed_at IS NULL`` and answered by the row count, so two
        simultaneous exchanges of one code cannot both succeed.
        """
        statement = (
            self.scoped_update(OAuthAuthorizationCode)
            .where(
                OAuthAuthorizationCode.id == code_id,
                OAuthAuthorizationCode.consumed_at.is_(None),
            )
            .values(consumed_at=at)
        )
        return await self._affected_rows(statement) == 1

    async def upsert_grant(
        self, *, client_id: str, scopes: frozenset[Scope], at: datetime
    ) -> GrantRecord:
        """Create or refresh this tenant's grant for a client, and return it.

        Re-consenting refreshes the scopes and clears any prior revocation rather than
        creating a second family, because two live families for one client would mean
        revoking one leaves the other issuing tokens. One statement, so two consents
        arriving together cannot both insert.
        """
        statement = (
            pg_insert(OAuthGrant)
            .values(
                id=uuid4(),
                tenant_id=self.tenant_id,
                client_id=client_id,
                scope=format_scopes(scopes),
                authorized_at=at,
            )
            .on_conflict_do_update(
                index_elements=[TENANT_ID_COLUMN, "client_id"],
                set_={"scope": format_scopes(scopes), "authorized_at": at, "revoked_at": None},
            )
            .returning(OAuthGrant)
        )
        stored = (await self._session.execute(statement)).scalar_one()
        return _as_grant(stored)

    async def find_grant_for_client(self, client_id: str) -> GrantRecord | None:
        """This tenant's grant for a client, or ``None``."""
        statement = self.scoped_select(OAuthGrant).where(OAuthGrant.client_id == client_id)
        found = await self._session.scalar(statement)
        return _as_grant(found) if found is not None else None

    async def create_refresh_token(
        self,
        *,
        token_id: str,
        grant_id: UUID,
        scopes: frozenset[Scope],
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        """Persist a freshly minted refresh token."""
        self._session.add(
            OAuthRefreshToken(
                id=token_id,
                tenant_id=self.tenant_id,
                grant_id=grant_id,
                scope=format_scopes(scopes),
                created_at=created_at,
                expires_at=expires_at,
            )
        )
        await self._session.flush()

    async def consume_refresh_token(self, token_id: str, at: datetime) -> bool:
        """Mark a refresh token exchanged. ``False`` when it was already exchanged.

        The same guarded update as :meth:`consume_code`, and for the same reason: rotation
        is only a defense if exactly one of two simultaneous exchanges can win.
        """
        statement = (
            self.scoped_update(OAuthRefreshToken)
            .where(
                OAuthRefreshToken.id == token_id,
                OAuthRefreshToken.consumed_at.is_(None),
                OAuthRefreshToken.revoked_at.is_(None),
            )
            .values(consumed_at=at)
        )
        return await self._affected_rows(statement) == 1

    async def revoke_family(self, grant_id: UUID, at: datetime) -> int:
        """Revoke a grant and every refresh token issued under it. Returns how many.

        The grant goes with the tokens deliberately. Revoking only the tokens would leave
        an unexpired authorization code able to establish a fresh chain on the same
        family, which is the opposite of what a detected replay should allow.
        """
        tokens = await self._affected_rows(
            self.scoped_update(OAuthRefreshToken)
            .where(OAuthRefreshToken.grant_id == grant_id, OAuthRefreshToken.revoked_at.is_(None))
            .values(revoked_at=at)
        )
        await self._affected_rows(
            self.scoped_update(OAuthGrant)
            .where(OAuthGrant.id == grant_id, OAuthGrant.revoked_at.is_(None))
            .values(revoked_at=at)
        )
        return tokens

    async def delete_expired_codes(self, before: datetime) -> int:
        """Remove codes past their expiry. Returns how many."""
        return await self._affected_rows(
            self.scoped_delete(OAuthAuthorizationCode).where(
                OAuthAuthorizationCode.expires_at < before
            )
        )

    async def delete_expired_refresh_tokens(self, before: datetime) -> int:
        """Remove refresh tokens past their expiry. Returns how many."""
        return await self._affected_rows(
            self.scoped_delete(OAuthRefreshToken).where(OAuthRefreshToken.expires_at < before)
        )

    async def delete_grants_revoked_before(self, before: datetime) -> int:
        """Remove grants revoked longer ago than the retention window. Returns how many.

        Their refresh tokens go with them through the foreign key's cascade, so a
        revoked family cannot leave rows behind that reference a grant that is gone.
        """
        return await self._affected_rows(
            self.scoped_delete(OAuthGrant).where(
                OAuthGrant.revoked_at.is_not(None), OAuthGrant.revoked_at < before
            )
        )


def _as_client(client: OAuthClient) -> ClientRecord:
    return ClientRecord(
        id=client.id,
        name=client.name,
        redirect_uris=tuple(client.redirect_uris),
        allowed_scopes=scopes_of(client.allowed_scopes),
        loopback_only=client.loopback_only,
    )


def _as_code(code: OAuthAuthorizationCode) -> AuthorizationCodeRecord:
    return AuthorizationCodeRecord(
        id=code.id,
        tenant_id=code.tenant_id,
        client_id=code.client_id,
        redirect_uri=code.redirect_uri,
        scopes=scopes_of(code.scope),
        code_challenge=code.code_challenge,
        created_at=code.created_at,
        expires_at=code.expires_at,
        consumed_at=code.consumed_at,
    )


def _as_grant(grant: OAuthGrant) -> GrantRecord:
    return GrantRecord(
        id=grant.id,
        tenant_id=grant.tenant_id,
        client_id=grant.client_id,
        scopes=scopes_of(grant.scope),
        authorized_at=grant.authorized_at,
        revoked_at=grant.revoked_at,
    )


def _as_refresh_token(token: OAuthRefreshToken) -> RefreshTokenRecord:
    return RefreshTokenRecord(
        id=token.id,
        tenant_id=token.tenant_id,
        grant_id=token.grant_id,
        scopes=scopes_of(token.scope),
        created_at=token.created_at,
        expires_at=token.expires_at,
        consumed_at=token.consumed_at,
        revoked_at=token.revoked_at,
    )
