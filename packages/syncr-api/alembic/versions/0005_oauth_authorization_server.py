"""the OAuth Authorization Server

Four tables and one seeded row.

``oauth_clients`` is deployment configuration rather than a tenant's data: it is read by the
presented ``client_id`` before any tenant is known, one registry serves the deployment, and it
is registered in ``syncr_api.core.tenancy.IDENTITY_TABLES`` on those grounds. Its one row is
inserted here, because P0 has no dynamic client registration: the CLI is the only client, so an
open registration endpoint would be an attack surface for a capability nothing needs.

The other three carry a non-null ``tenant_id`` and an index leading with it. None carries a
``user_id``: a tenant holds exactly one user permanently, so a code, a grant, and a refresh
token have no user dimension to disagree about.

Every secret is stored as a digest. The primary key of a code and of a refresh token is the
SHA-256 of the value the client holds, so this schema contains nothing that can be presented
anywhere.

Every foreign key cascades on delete, so removing a tenant removes its grants, and removing a
grant removes the refresh tokens issued under it, leaving no row that references something
that no longer exists.

Revision ID: 0005_oauth_authorization_server
Revises: 0004_plan_storage
Create Date: 2026-08-02

"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_oauth_authorization_server"
# The head this branch was cut from was `0002_tenancy_users_sessions`, and this wave adds three
# migrations over disjoint tables. They are chained rather than left as three heads, because
# three heads make `alembic upgrade head` an error for every ticket in the wave, including the
# ones that only need the schema to exist.
down_revision: str | None = "0004_plan_storage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The seeded client. The values are the same ones `syncr_api.oauth.config` names, restated here
# because a migration must not import application code: a migration is a record of what was
# applied, and importing a constant would let a later edit to that constant silently change
# what this revision means.
_CLI_CLIENT_ID = "syncr-cli"
_CLI_CLIENT_NAME = "syncr CLI"
_CLI_CLIENT_SCOPES = "plan:read plan:write"
_CLI_REDIRECT_URIS = ["http://127.0.0.1/callback", "http://[::1]/callback"]

# SHA-256, as 64 lowercase hex characters.
_DIGEST_LENGTH = 64
_CLIENT_ID_LENGTH = 64
_CLIENT_NAME_LENGTH = 120
_REDIRECT_URI_LENGTH = 2000
_SCOPE_LENGTH = 200
_CHALLENGE_LENGTH = 128


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("id", sa.String(_CLIENT_ID_LENGTH), nullable=False),
        sa.Column("name", sa.String(_CLIENT_NAME_LENGTH), nullable=False),
        sa.Column("redirect_uris", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("allowed_scopes", sa.String(_SCOPE_LENGTH), nullable=False),
        sa.Column("loopback_only", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_clients")),
    )
    op.create_table(
        "oauth_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.String(_CLIENT_ID_LENGTH), nullable=False),
        sa.Column("scope", sa.String(_SCOPE_LENGTH), nullable=False),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["oauth_clients.id"],
            name=op.f("fk_oauth_grants_client_id_oauth_clients"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_oauth_grants_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_grants")),
    )
    # A unique INDEX rather than a unique constraint: it enforces one live grant per tenant and
    # client, and it is also the index the tenant scope is served from.
    op.create_index(
        "uq_oauth_grants_tenant_id_client_id",
        "oauth_grants",
        ["tenant_id", "client_id"],
        unique=True,
    )
    op.create_table(
        "oauth_authorization_codes",
        sa.Column("id", sa.String(_DIGEST_LENGTH), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.String(_CLIENT_ID_LENGTH), nullable=False),
        sa.Column("redirect_uri", sa.String(_REDIRECT_URI_LENGTH), nullable=False),
        sa.Column("scope", sa.String(_SCOPE_LENGTH), nullable=False),
        sa.Column("code_challenge", sa.String(_CHALLENGE_LENGTH), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["oauth_clients.id"],
            name=op.f("fk_oauth_authorization_codes_client_id_oauth_clients"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_oauth_authorization_codes_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_authorization_codes")),
    )
    op.create_index(
        "ix_oauth_authorization_codes_tenant_id_expires_at",
        "oauth_authorization_codes",
        ["tenant_id", "expires_at"],
    )
    op.create_table(
        "oauth_refresh_tokens",
        sa.Column("id", sa.String(_DIGEST_LENGTH), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(_SCOPE_LENGTH), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["grant_id"],
            ["oauth_grants.id"],
            name=op.f("fk_oauth_refresh_tokens_grant_id_oauth_grants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_oauth_refresh_tokens_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_refresh_tokens")),
    )
    op.create_index(
        "ix_oauth_refresh_tokens_tenant_id_grant_id",
        "oauth_refresh_tokens",
        ["tenant_id", "grant_id"],
    )
    _seed_cli_client()


def downgrade() -> None:
    op.drop_index("ix_oauth_refresh_tokens_tenant_id_grant_id", table_name="oauth_refresh_tokens")
    op.drop_table("oauth_refresh_tokens")
    op.drop_index(
        "ix_oauth_authorization_codes_tenant_id_expires_at",
        table_name="oauth_authorization_codes",
    )
    op.drop_table("oauth_authorization_codes")
    op.drop_index("uq_oauth_grants_tenant_id_client_id", table_name="oauth_grants")
    op.drop_table("oauth_grants")
    op.drop_table("oauth_clients")


def _seed_cli_client() -> None:
    """Register the one client P0 serves.

    Idempotent on the client id, so re-applying this revision against a database that already
    holds the row changes nothing rather than failing.
    """
    clients = sa.table(
        "oauth_clients",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("redirect_uris", postgresql.JSONB(astext_type=sa.Text())),
        sa.column("allowed_scopes", sa.String),
        sa.column("loopback_only", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        postgresql.insert(clients)
        .values(
            id=_CLI_CLIENT_ID,
            name=_CLI_CLIENT_NAME,
            redirect_uris=_CLI_REDIRECT_URIS,
            allowed_scopes=_CLI_CLIENT_SCOPES,
            loopback_only=True,
            created_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
