"""habits: the walked charge as a stored column, restated by the outcome write

``habits.charged_misses`` holds what ``syncr_domain.debt``'s walk answers for one habit: confirmed
skips, less the make-up completions settled against them, floored per credit, oldest-due first.

Before this column, every reader that answered a habit's debt walked the whole outcome log. The
walk is what makes the figure exact, but the rows it needs are unbounded: they grow with the
tenant's history forever. The figure is now stored and restated inside the transaction that changed
the log, so a request answers from the row instead of walking history, and the figure cannot fall
when part of a habit's history ages out of any window a read takes -- there is no such window left
in the debt's path.

The rotation cursor deliberately does NOT get a column. It is a count of confirmed completions
modulo the variant list, so dropping any single completion moves every later week onto the wrong
variant: no window can serve it, and storing its answer would be storing a value nothing re-derives.
It stays derived over the whole log.

**Existing rows are backfilled by walking the log here**, with the same rules the live walk applies,
spelled in this file rather than imported: a revision replays against databases at its own point in
the chain, so it must not read the workspace's current code. The walk orders each habit's rows by
the instant the occurrence came due, charges one per confirmed skip, and discharges one per
completed make-up, never below zero -- the floor keeps a credit whose own charge was later corrected
away from settling an unrelated miss.

Every literal below is spelled rather than imported, for the reason above.

Revision ID: sr_plan_20_charged_misses
Revises: sr_plan_18_largest_gap
Create Date: 2026-09-16

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Kept inside 32 characters, which is what `alembic_version.version_num` holds. Numbered for the
# ticket that adds it rather than sequentially: sibling tickets add a revision over disjoint tables
# in the same wave, so a shared counter would collide while the ticket number cannot.
revision: str = "sr_plan_20_charged_misses"
down_revision: str | None = "sr_plan_18_largest_gap"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "habits"
COLUMN = "charged_misses"

OUTCOMES = "block_outcomes"
KIND = "binding->>'kind'"
ENTITY = "binding->>'entity_id'"
MAKE_UP = "binding->>'make_up'"
HABIT_KIND = "habit"
SKIPPED = "skipped"
COMPLETED = "completed"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(COLUMN, sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_check_constraint("charged_misses_is_a_count", TABLE, f"{COLUMN} >= 0")
    _backfill()
    op.alter_column(TABLE, COLUMN, server_default=None)


def downgrade() -> None:
    op.drop_constraint("charged_misses_is_a_count", TABLE, type_="check")
    op.drop_column(TABLE, COLUMN)


def _backfill() -> None:
    """Walk every habit's rows once and store what the live derivation would answer."""
    # The SQL structure comes only from fixed migration constants; dynamic values are bound below.
    rows = sa.text(
        f"SELECT tenant_id, {ENTITY} AS habit_id, state, occurred_at, confirmed_at, {MAKE_UP}"  # noqa: S608
        f" FROM {OUTCOMES} WHERE {KIND} = '{HABIT_KIND}'"
        " ORDER BY habit_id, occurred_at, binding->>'make_up'"
    )
    charges: dict[tuple[str, str], int] = {}
    for tenant_id, habit_id, state, _occurred_at, confirmed_at, make_up in op.get_bind().execute(
        rows
    ):
        if confirmed_at is None:
            continue
        key = (str(tenant_id), str(habit_id))
        if state == SKIPPED:
            charges[key] = charges.get(key, 0) + 1
        elif state == COMPLETED and make_up == "true":
            charges[key] = max(charges.get(key, 0) - 1, 0)
    for (tenant_id, habit_id), charged in charges.items():
        if charged:
            op.execute(
                sa.text(
                    f"UPDATE {TABLE} SET {COLUMN} = :charged"  # noqa: S608
                    " WHERE id = :habit_id AND tenant_id = :tenant_id"
                ).bindparams(tenant_id=tenant_id, habit_id=habit_id, charged=charged)
            )
