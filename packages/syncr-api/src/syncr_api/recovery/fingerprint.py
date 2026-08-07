"""What a restore is checked against: every table's row count, every rotation cursor, and the head.

The restore drill's pass condition is **data read back**, not an exit status. ``pg_restore`` exits 0
having restored an empty archive, and a database with a schema and no rows is exactly the outcome an
untested backup path produces. So the drill compares two readings of this shape: one taken against
the live database before the dump, one taken against the restored copy.

**The rotation cursor is here because it is derived rather than stored.** Row counts prove the rows
arrived; they say nothing about whether the projections over them still resolve. The cursor is the
projection the product would visibly get wrong: ``Gym`` is on ``Legs`` *because* ``Chest & Back``
was confirmed complete, and it is re-derived from the outcome log on every read. A restore that
dropped one confirmation restores a plausible database whose next session trains the wrong muscle
group, and nothing but this reading would notice.

**Why the counts are a floor rather than an equality.** This reading is taken before ``pg_dump``
opens its snapshot, so the dump is at or after it and the restored copy is a SUPERSET: every count
must be at least the count recorded here. A count that came back LOWER is data the restore lost.
The window is the seconds between the two, at 03:00, on a deployment with one user; a cursor that
moved inside it is reported as a failure rather than tolerated, because the alternative is a
comparison that cannot distinguish a write from a loss.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import func, select

from syncr_api.accounts.repository import TenantRepository
from syncr_api.habits.repository import HabitRepository
from syncr_api.plans.habit_log import HabitOutcomeLog
from syncr_api.recovery.tables import registered_tables
from syncr_domain.cursor import cursor_reading

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_domain.identifiers import TenantId

# The document's own keys. `deployments/ops/fingerprint.py` reads the same names from the other side
# of a bucket, in another interpreter, with no import between them, so the two sets are crossed as
# an equality by `packages/syncr-api/tests/test_recovery_fingerprint.py`.
DOCUMENT_VERSION: Final = 1
KEY_VERSION: Final = "version"
KEY_TAKEN_AT: Final = "taken_at"
KEY_EXPECTED_HEAD: Final = "expected_head"
KEY_APPLIED_REVISION: Final = "applied_revision"
KEY_ROW_COUNTS: Final = "row_counts"
KEY_CURSORS: Final = "cursors"
KEY_CURSOR_KEY: Final = "key"
KEY_CURSOR_INDEX: Final = "index"
KEY_CURSOR_VARIANT: Final = "variant"
KEY_CURSOR_COMPLETIONS: Final = "confirmed_completions"


@dataclass(frozen=True, slots=True)
class CursorFact:
    """One rotation habit's derived cursor, keyed so one habit is comparable across a restore."""

    key: str
    index: int
    variant: str
    confirmed_completions: int


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """One reading of a database, in the form the drill compares."""

    taken_at: datetime
    expected_head: str
    applied_revision: str | None
    row_counts: Mapping[str, int]
    cursors: tuple[CursorFact, ...]

    def as_document(self) -> dict[str, Any]:
        """The JSON-ready form, which is the whole contract with the ops package."""
        return {
            KEY_VERSION: DOCUMENT_VERSION,
            KEY_TAKEN_AT: self.taken_at.isoformat(),
            KEY_EXPECTED_HEAD: self.expected_head,
            KEY_APPLIED_REVISION: self.applied_revision,
            KEY_ROW_COUNTS: dict(sorted(self.row_counts.items())),
            KEY_CURSORS: [
                {
                    KEY_CURSOR_KEY: fact.key,
                    KEY_CURSOR_INDEX: fact.index,
                    KEY_CURSOR_VARIANT: fact.variant,
                    KEY_CURSOR_COMPLETIONS: fact.confirmed_completions,
                }
                for fact in self.cursors
            ],
        }


async def read_fingerprint(
    session: AsyncSession,
    *,
    now: datetime,
    expected_head: str,
    applied_revision: str | None,
) -> Fingerprint:
    """Read every count and every cursor this database holds.

    Cross-tenant by construction, which is why the tenant list is enumerated and the cursor read is
    built per tenant through the scoped repositories: the same shape the observability duties use,
    for the same reason. The counts are not scoped, because a count of every row is the question.
    """
    return Fingerprint(
        taken_at=now,
        expected_head=expected_head,
        applied_revision=applied_revision,
        row_counts=await _row_counts(session),
        cursors=await _cursors(session),
    )


async def _row_counts(session: AsyncSession) -> dict[str, int]:
    """Every declared table's row count, schema-qualified as ``pg_restore --list`` prints it.

    The tables come from the declarative metadata rather than from a list here, so a feature module
    that adds one is counted, dumped, and checked after a restore without this file being edited.
    """
    counts: dict[str, int] = {}
    for table in registered_tables():
        total = await session.scalar(select(func.count()).select_from(table))
        counts[f"{table.schema or 'public'}.{table.name}"] = int(total or 0)
    return counts


async def _cursors(session: AsyncSession) -> tuple[CursorFact, ...]:
    """Every rotation habit's cursor, across every tenant, derived from the outcome log."""
    tenants = await TenantRepository(session).list_ids()
    facts: list[CursorFact] = []
    for tenant_id in tenants:
        facts.extend(await _tenant_cursors(session, tenant_id))
    return tuple(sorted(facts, key=lambda fact: fact.key))


async def _tenant_cursors(session: AsyncSession, tenant_id: TenantId) -> list[CursorFact]:
    records = await HabitRepository(session, tenant_id).list_all()
    if not records:
        return []
    outcomes = await HabitOutcomeLog(session, tenant_id).read([record.id for record in records])
    facts: list[CursorFact] = []
    for record in records:
        reading = cursor_reading(record.as_habit(), outcomes)
        if reading is None:
            continue
        facts.append(
            CursorFact(
                key=f"{tenant_id}/{record.id}",
                index=reading.index,
                variant=reading.variant,
                confirmed_completions=reading.confirmed_completions,
            )
        )
    return facts
