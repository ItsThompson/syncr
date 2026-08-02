"""baseline (empty)

Establishes the migration chain root and creates the ``alembic_version`` table on
``upgrade head``. No schema yet: this baseline is database plumbing only, and the
first domain tables arrive in a later revision on top of it.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-08-02

"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
