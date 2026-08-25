"""operations.session_mode_active: the requesting caller's statement about the weekly session

An operation a mutation schedules is the only object that crosses from the request to the worker,
so it is what carries the caller's answer to whether the weekly session was open. Without a column,
the solve's recorder could only bind the ``NO_SESSION_IS_OPEN`` literal, and every episode a
withdrawal, an approval, an outcome or a declaration opened was recorded as a miss however the
request answered.

The statement is written when the operation is created and widened when one is joined: a request
that coalesces into an operation already in flight flags it if it states the session was open,
because several requests share the one solve and any of them may have been asked during a session.
Rows that predate this revision were all scheduled by callers that had no way to state anything,
so each takes ``false``, which is what those callers were.

Every literal below is spelled here rather than imported. A revision describes the schema at its
own point in the chain and is replayed forever against databases at that point, so a value read
from the workspace's live code would describe the schema as it is now instead.

Revision ID: sr_deploy_03_operation_session
Revises: drop_areas_default_preference
Create Date: 2026-08-10

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "sr_deploy_03_operation_session"
down_revision: str | None = "drop_areas_default_preference"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "operations"
COLUMN = "session_mode_active"


def upgrade() -> None:
    # A server default so the NOT NULL holds for the rows that already exist, then dropped, because
    # the model states the default on the Python side and a default left here would be schema the
    # model does not describe.
    op.add_column(TABLE, sa.Column(COLUMN, sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column(TABLE, COLUMN, server_default=None)


def downgrade() -> None:
    op.drop_column(TABLE, COLUMN)
