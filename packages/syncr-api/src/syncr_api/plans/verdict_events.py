"""``VerdictEventRepository``: the transition corpus, and the two reads the rule needs.

``VE1`` says a row is appended, never updated and never pruned, so this extends
:class:`~syncr_api.core.repository.TenantScopedReader`, which carries no ``UPDATE`` and no
``DELETE`` builder at all. The rule is a shape rather than a sentence a future reader has to find,
and the retention guard in ``tests/test_plan_storage_boundary.py`` reads the same shape.

``VE5`` is the caller's to hold and this module's to make possible: the append takes no transaction
of its own and opens no session, so a transition commits with the request or job that computed it or
not at all.

Two reads rather than one. :meth:`latest` is what the transition rule compares against, one indexed
row per decision, and it is the whole cost of a tick that changes nothing. :meth:`for_week` hands
back the week's rows oldest first, which is the order the episode definition is stated in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import insert

from syncr_api.core.repository import TenantScopedReader
from syncr_api.core.tenancy import TENANT_ID_COLUMN
from syncr_api.plans.facts import VerdictEvent
from syncr_api.plans.records import VerdictEventRecord
from syncr_api.plans.stored_values import read_list, read_member
from syncr_api.plans.surfaces import VerdictSurface
from syncr_domain.feasibility import Provenance, ShortfallKind
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from sqlalchemy import Select

    from syncr_api.plans.declarations import VerdictToRecord


class VerdictEventRepository(TenantScopedReader):
    """One tenant's verdict transitions. Appended, never changed, never removed."""

    async def append(self, transition: VerdictToRecord) -> VerdictEventRecord:
        """Record one transition, and answer with the row as it was stored.

        The record rather than the id, because the caller that wrote it reports the direction it
        moved in and the metric job reads the same fields back: a writer that answered with an id
        would make its own log line and its own counter read a second source.
        """
        written = await self._session.scalars(
            insert(VerdictEvent)
            .values(
                [
                    {
                        "id": uuid4(),
                        TENANT_ID_COLUMN: self.tenant_id,
                        "iso_week": str(transition.iso_week),
                        "occurred_at": transition.occurred_at,
                        "provenance": transition.provenance.value,
                        "feasible": transition.feasible,
                        "shortfall_minutes": transition.shortfall_minutes,
                        "shortfall_kinds": [one.value for one in transition.shortfall_kinds],
                        "surface": transition.surface.value,
                        "session_mode_active": transition.session_mode_active,
                        "input_version": transition.input_version,
                        "caused_by_operation_id": transition.caused_by_operation_id,
                    }
                ]
            )
            .returning(VerdictEvent)
        )
        return _as_record(written.one())

    async def latest(self, iso_week: IsoWeek) -> VerdictEventRecord | None:
        """The newest transition recorded for this week, or ``None`` for a week with none."""
        found = await self._session.scalar(self._week(iso_week).order_by(*_NEWEST_FIRST).limit(1))
        return None if found is None else _as_record(found)

    async def for_week(self, iso_week: IsoWeek) -> list[VerdictEventRecord]:
        """Every transition this week holds, oldest first: the order an episode is read in."""
        rows = await self._session.scalars(self._week(iso_week).order_by(*_OLDEST_FIRST))
        return [_as_record(row) for row in rows]

    def _week(self, iso_week: IsoWeek) -> Select[tuple[VerdictEvent]]:
        return self.scoped_select(VerdictEvent).where(VerdictEvent.iso_week == str(iso_week))


# The order both reads are stated in, and the id is a tie-break rather than an order anyone reads:
# two transitions recorded against one instant would otherwise come back in whichever order the scan
# produced, and "the last thing said about this week" has to be one row.
#
# `occurred_at` is the verdict's own instant rather than an insertion stamp, so `latest` answers
# with the NEWEST verdict rather than the last row written: a writer holding an older verdict does
# not displace a newer one. The episode definition reads the same order, so a week's episodes are
# grouped by when its verdicts were computed rather than by when they reached the table.
_NEWEST_FIRST = (VerdictEvent.occurred_at.desc(), VerdictEvent.id.desc())
_OLDEST_FIRST = (VerdictEvent.occurred_at.asc(), VerdictEvent.id.asc())


def _as_record(event: VerdictEvent) -> VerdictEventRecord:
    return VerdictEventRecord(
        id=event.id,
        tenant_id=event.tenant_id,
        iso_week=IsoWeek.parse(event.iso_week),
        occurred_at=event.occurred_at,
        # Both columns hold a closed set the database enforces, so the enum is read back rather than
        # validated: a value outside it cannot be stored while the check constraint holds.
        provenance=Provenance(event.provenance),
        feasible=event.feasible,
        shortfall_minutes=event.shortfall_minutes,
        shortfall_kinds=tuple(
            # The column is JSONB, which no constraint reaches, so a member outside the vocabulary
            # is a stated refusal rather than a `ValueError` from an enum call.
            read_member(ShortfallKind, one, field="shortfallKinds")
            for one in read_list(event.shortfall_kinds, field="shortfallKinds")
        ),
        surface=VerdictSurface(event.surface),
        session_mode_active=event.session_mode_active,
        input_version=event.input_version,
        caused_by_operation_id=event.caused_by_operation_id,
    )
