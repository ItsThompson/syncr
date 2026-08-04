"""the Google grant, and what one provider read cost

Two things, both for the one OAuth integration in P0.

``google_credentials`` holds the account connection: one row per tenant, enforced by a unique
index, because syncr connects one account and two rows would mean two refresh tokens with no rule
for choosing. The refresh token is stored as CIPHERTEXT and only as ciphertext, so a database dump,
a backup, and a replica carry no usable authority; the key lives in the environment, which is the
one place a dump does not reach.

The failure pair is a check constraint rather than a convention. ``refresh_failing_since`` and
``last_refresh_error`` are both set or both null, because the notice built from them states how long
writes have been failing AND why, and half that pair is a notice that cannot be rendered. The
instant is when failing STARTED, not when it last failed: a field that moved on every retry would
report "failing for 15 minutes" after a week of failing.

``calendar_sources`` gains two columns, both about what a provider did rather than what a feed
holds. ``attempts`` is how many calls the last read made, which is how a rate-limited source reports
that it backed off instead of looking slow. ``resync_reason`` is why a read was a full one while an
incremental cursor was held, because a source silently re-reading a whole calendar every poll looks
healthy and is not.

Every value this revision names is spelled out here rather than imported. A revision describes the
schema at its own point in the chain and is replayed against databases at that point, so a CHECK
built from a live constant names whatever that constant holds today.

The chain: ``down_revision`` is the head recorded when this work reached the migration, which by
then was the habits revision. Five siblings landed revisions in the same wave over disjoint tables,
so the order between them decides nothing; a single head is what ``alembic upgrade head`` needs.

Revision ID: 0018_google_calendar
Revises: 0014_habits
Create Date: 2026-08-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Kept inside 32 characters, which is what `alembic_version.version_num` holds.
revision: str = "0018_google_calendar"
down_revision: str | None = "0014_habits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREDENTIALS = "google_credentials"
SOURCES = "calendar_sources"


def upgrade() -> None:
    op.create_table(
        CREDENTIALS,
        sa.Column("id", sa.Uuid(), nullable=False),
        # Fernet ciphertext of the refresh token. Wider than the plaintext it holds, because
        # encryption and base64 both add to it.
        sa.Column("encrypted_refresh_token", sa.String(length=4096), nullable=False),
        # Space separated, as Google's token response states them. What was GRANTED, which can be
        # narrower than what was requested: a user may untick a scope on the consent screen.
        sa.Column("granted_scopes", sa.String(length=1024), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_refresh_at", sa.DateTime(timezone=True), nullable=True),
        # When refreshing STARTED failing. The notice states a duration.
        sa.Column("refresh_failing_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refresh_error", sa.String(length=500), nullable=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(refresh_failing_since IS NULL) = (last_refresh_error IS NULL)",
            name=op.f(f"ck_{CREDENTIALS}_a_refresh_failure_states_when_and_why"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{CREDENTIALS}_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{CREDENTIALS}")),
    )
    # One Google account per tenant. A unique INDEX rather than a unique CONSTRAINT, matching the
    # convention the calendar tables set.
    op.create_index(f"uq_{CREDENTIALS}_tenant_id", CREDENTIALS, ["tenant_id"], unique=True)

    # Added with a server default so the column is non-null on rows that already exist, and the
    # default is then dropped: what writes this value is the syncer, and a default left in place
    # would let a future INSERT that forgets it look like a read that made no calls.
    op.add_column(
        SOURCES, sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0"))
    )
    op.alter_column(SOURCES, "attempts", server_default=None)
    op.add_column(SOURCES, sa.Column("resync_reason", sa.String(length=500), nullable=True))
    op.create_check_constraint(
        op.f(f"ck_{SOURCES}_attempts_are_not_negative"), SOURCES, "attempts >= 0"
    )


def downgrade() -> None:
    op.drop_constraint(op.f(f"ck_{SOURCES}_attempts_are_not_negative"), SOURCES, type_="check")
    op.drop_column(SOURCES, "resync_reason")
    op.drop_column(SOURCES, "attempts")
    op.drop_index(f"uq_{CREDENTIALS}_tenant_id", table_name=CREDENTIALS)
    op.drop_table(CREDENTIALS)
