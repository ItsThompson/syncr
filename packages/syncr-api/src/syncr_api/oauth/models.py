"""The four Authorization Server tables.

``oauth_clients`` is deployment configuration and carries no tenant. It is read by the
presented ``client_id`` before any tenant is known, which is the same reason ``users`` and
``sessions`` are exempt from the scope, and it is registered in
:data:`~syncr_api.core.tenancy.IDENTITY_TABLES` on those grounds: it establishes the
identity of a CLIENT the way those two establish the identity of a person and a browser.
One client registry serves the deployment, so there is no scope for it to prove.

The other three are tenant-scoped, and none of them carries a ``user_id``. A tenant holds
exactly one user permanently, so a code, a grant, and a refresh token have no user
dimension to disagree about; the access token's subject is resolved from the tenant at
issuance.

Every secret is stored as a digest and never as itself, so the primary key of a code and of
a refresh token is the SHA-256 of the value the client holds. A dump of these tables
therefore yields nothing that can be presented anywhere.
"""

# NO `from __future__ import annotations`, for the same reason
# `syncr_api.core.tenancy` omits it: SQLAlchemy resolves the TenantScoped mixin's
# `Mapped[...]` annotation in the namespace of the subclass applying it, and a postponed
# annotation is a string that subclass would have to import a name to resolve.
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from syncr_api.core.orm import Base
from syncr_api.core.tenancy import TENANT_ID_COLUMN, TenantScoped
from syncr_api.oauth.secrets import DIGEST_LENGTH

# A client id is a chosen name (`syncr-cli`), not a minted secret, so it is bounded like a
# name. A redirect URI is bounded at the length a browser will carry.
CLIENT_ID_MAX_LENGTH = 64
CLIENT_NAME_MAX_LENGTH = 120
REDIRECT_URI_MAX_LENGTH = 2000
# Three scopes, space separated, with room for the fourth nobody has argued for yet.
SCOPE_MAX_LENGTH = 200

OAUTH_CLIENTS_TABLE = "oauth_clients"
OAUTH_AUTHORIZATION_CODES_TABLE = "oauth_authorization_codes"
OAUTH_GRANTS_TABLE = "oauth_grants"
OAUTH_REFRESH_TOKENS_TABLE = "oauth_refresh_tokens"


class OAuthClient(Base):
    """A registered client. Deployment configuration, seeded by the migration."""

    __tablename__ = OAUTH_CLIENTS_TABLE

    id: Mapped[str] = mapped_column(String(CLIENT_ID_MAX_LENGTH), primary_key=True)
    name: Mapped[str] = mapped_column(String(CLIENT_NAME_MAX_LENGTH), nullable=False)
    # JSONB rather than a child table: the list is read whole on every authorize request
    # and is never queried into, so a join would buy nothing and cost a table.
    redirect_uris: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    # The ceiling on what this client may ever request, space separated. A request for
    # anything outside it is refused whatever the user consents to, which is what keeps a
    # stolen CLI token away from `admin`.
    allowed_scopes: Mapped[str] = mapped_column(String(SCOPE_MAX_LENGTH), nullable=False)
    # A public client that cannot hold a secret may only redirect to this machine.
    loopback_only: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OAuthAuthorizationCode(Base, TenantScoped):
    """A single-use code, bound to a tenant, a client, and a PKCE challenge.

    Single use is enforced by ``consumed_at``, not by deletion: a consumed row is what lets
    a replay be recognized and logged rather than merely failing to find anything.
    """

    __tablename__ = OAUTH_AUTHORIZATION_CODES_TABLE

    id: Mapped[str] = mapped_column(String(DIGEST_LENGTH), primary_key=True)
    client_id: Mapped[str] = mapped_column(
        String(CLIENT_ID_MAX_LENGTH),
        ForeignKey(f"{OAUTH_CLIENTS_TABLE}.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The exact URI the code was issued against. The exchange compares it, so a code
    # cannot be redeemed by a client that then names a different destination.
    redirect_uri: Mapped[str] = mapped_column(String(REDIRECT_URI_MAX_LENGTH), nullable=False)
    scope: Mapped[str] = mapped_column(String(SCOPE_MAX_LENGTH), nullable=False)
    code_challenge: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Leads with the tenant, as every composite index in this schema does, and closes on
    # the column the sweep filters by.
    __table_args__ = (
        Index("ix_oauth_authorization_codes_tenant_id_expires_at", TENANT_ID_COLUMN, "expires_at"),
    )


class OAuthGrant(Base, TenantScoped):
    """One tenant's standing authorization of one client. The family a token belongs to."""

    __tablename__ = OAUTH_GRANTS_TABLE

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    client_id: Mapped[str] = mapped_column(
        String(CLIENT_ID_MAX_LENGTH),
        ForeignKey(f"{OAUTH_CLIENTS_TABLE}.id", ondelete="CASCADE"),
        nullable=False,
    )
    scope: Mapped[str] = mapped_column(String(SCOPE_MAX_LENGTH), nullable=False)
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # One live grant per tenant and client, so re-consenting refreshes the existing family
    # rather than growing a second one that the first cannot revoke. Declared as a unique
    # INDEX rather than a unique constraint, because the schema rule is that every table
    # holding a plan has an index whose first column is the tenant: a constraint enforces the
    # same uniqueness but is not an index the scope can be served from.
    __table_args__ = (
        Index(
            "uq_oauth_grants_tenant_id_client_id",
            TENANT_ID_COLUMN,
            "client_id",
            unique=True,
        ),
    )


class OAuthRefreshToken(Base, TenantScoped):
    """A rotating refresh token. Consumed on use, and revocable with its whole family.

    ``consumed_at`` and ``revoked_at`` are separate columns because they answer different
    questions. Consumed means "this one was exchanged and a successor exists", which is the
    normal end of a refresh token's life; revoked means "this family is finished", which is
    what a sign-out or a detected replay does. A replay of a consumed token is what reveals
    a stolen one, so the record of the consumption has to outlive the exchange.
    """

    __tablename__ = OAUTH_REFRESH_TOKENS_TABLE

    id: Mapped[str] = mapped_column(String(DIGEST_LENGTH), primary_key=True)
    grant_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{OAUTH_GRANTS_TABLE}.id", ondelete="CASCADE"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String(SCOPE_MAX_LENGTH), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Family revocation reads every row of one grant, and the tenant is always known by
    # then, so the index that serves it leads with the tenant like the rest.
    __table_args__ = (
        Index("ix_oauth_refresh_tokens_tenant_id_grant_id", TENANT_ID_COLUMN, "grant_id"),
    )
