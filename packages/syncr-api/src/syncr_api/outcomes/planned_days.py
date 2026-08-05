"""What each day of a range holds: its span, its plan of record, and the blocks that begin in it.

One module, because the alternative shape is the defect it exists to prevent. Every act in this
package needs the same three things per day, and a service that asked for them per date would read
one revision and rebuild one week's document PER DAY: a four-week count would issue over a hundred
statements and rebuild the same week five times. This reads each week's plan of record once and
answers for every date in the range from it.

**A revision is rebuilt through the domain constructors**, so a day's blocks satisfy every
invariant the domain states about a week before a ledger renders them or a confirmation records
them.

**A date the tenant's zones do not hold is passed over rather than reported.** ``Pacific/Apia``
skipped 30 December 2011, and a range spanning such a date covers one day fewer. A caller naming
one date directly gets a stated refusal instead, which is the boundary's decision rather than this
module's: what a range does with an absent day and what a single read does with one are different
answers to the same absence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.outcomes.days import blocks_of_the_day, dates_in, day_span
from syncr_api.plans.reality import Presumption
from syncr_api.plans.stored_documents import plan_document
from syncr_domain.intervals import Interval
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from syncr_api.plans.records import PlanRevisionRecord
    from syncr_api.plans.repository import PlanRepository
    from syncr_domain.plan import Block, PlanDocument
    from syncr_domain.zones import Date, ZoneProfile


@dataclass(frozen=True, slots=True, kw_only=True)
class PlannedDay:
    """One date, the instants it covers, and what the plan of record put in it.

    ``revision`` is ``None`` when the week holds no plan, and ``blocks`` is then empty. The two
    travel together because a block is recorded against the plan of record that placed it, and a
    caller holding one without the other could record an outcome against no revision at all.
    """

    on: Date
    span: Interval
    revision: PlanRevisionRecord | None
    blocks: tuple[Block, ...]

    def presumptions(self) -> tuple[Presumption, ...]:
        """What confirming this day has to record, which is one row per block it holds."""
        if self.revision is None:
            return ()
        return tuple(
            Presumption(
                block_id=block.id,
                binding=block.binding,
                revision_id=self.revision.id,
                occurred_at=block.interval.start,
            )
            for block in self.blocks
        )


@dataclass(frozen=True, slots=True)
class _StoredWeek:
    """One week's plan of record, read once and answered for by every date inside it."""

    revision: PlanRevisionRecord
    document: PlanDocument


class PlannedDayReader:
    """Reads the plan of record behind a range of local dates, one week at a time."""

    def __init__(self, plans: PlanRepository) -> None:
        self._plans = plans

    async def read(self, first: Date, last: Date, profile: ZoneProfile) -> tuple[PlannedDay, ...]:
        """Each date from ``first`` to ``last`` that the tenant's zones hold, in order."""
        dated = [
            (on, span)
            for on in dates_in(first, last)
            if (span := day_span(on, profile)) is not None
        ]
        stored = await self._weeks(IsoWeek.containing(on) for on, _ in dated)
        return tuple(_planned(on, span, stored.get(IsoWeek.containing(on))) for on, span in dated)

    async def _weeks(self, weeks: Iterable[IsoWeek]) -> dict[IsoWeek, _StoredWeek]:
        """Each named week's plan of record, read once however many dates name it."""
        found: dict[IsoWeek, _StoredWeek] = {}
        for week in sorted(set(weeks)):
            revision = await self._plans.latest(week)
            if revision is not None:
                found[week] = _StoredWeek(revision, plan_document(revision.document))
        return found


def spanning(days: Sequence[PlannedDay]) -> Interval | None:
    """The instants a whole range covers, for the one read that fetches its outcomes.

    ``None`` when the range holds no day the tenant's zones have. Built from the days' own bounds
    rather than from the dates, so a range whose first date is 23 hours long and whose last is 25
    covers exactly what its days do.
    """
    if not days:
        return None
    return Interval(days[0].span.start, days[-1].span.end)


def _planned(on: Date, span: Interval, stored: _StoredWeek | None) -> PlannedDay:
    if stored is None:
        return PlannedDay(on=on, span=span, revision=None, blocks=())
    return PlannedDay(
        on=on,
        span=span,
        revision=stored.revision,
        blocks=blocks_of_the_day(stored.document, span),
    )
