"""Which minutes a confirmed day gives an Area, and which days a period holds.

This is the pie review's numerator, and it is a different figure from the budget report's. The
budget report asks what a week PLANS to give each Area. A review asks what each Area actually
got, which is a narrower question in two ways, both stated
by the area-review requirement.

**Only a confirmed day contributes.** A day the user never answered for is a day whose blocks are
presumed, and presuming a week and then reporting it as behaviour is how a review comes to propose
a budget from an absence. So a day with no confirmation gives nothing, however many blocks it
holds.

**Off-plan spans are excluded entirely.** They are already out of the denominator, through the
interval union `syncr_domain.discretionary` subtracts, so leaving them in the numerator would
charge an Area time the denominator does not hold and let a wedge exceed the whole.

**What a block gives is the attribution table's answer, not its planned span.**
:func:`syncr_domain.outcomes.attributed_span` is that table: a skip gives nothing, a partial gives
the minutes it reported, and a move gives the interval it really happened in. There is exactly one
statement of it and this reads it rather than deciding again.

A day is classified in one pass, and the order of the questions is the order of their authority:

| The day | Reads as | Because |
|---|---|---|
| covered end to end by an off-plan period | off-plan | there was nothing to answer for |
| holding blocks, every one of them confirmed | confirmed | the user answered for it |
| holding blocks, not all of them confirmed | unconfirmed | the user has not answered for it |
| holding no block | neither | there is nothing to answer for, so counting it would report a
  backlog of days on which nothing was planned |

Off-plan outranks the rest because an off-plan day is a day the user declared away, and reporting
it among the unconfirmed ones would name a holiday as a lapse. That is exactly the separation
required: off-plan days are reported separately from unconfirmed days.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.intervals import IntervalSet
from syncr_domain.outcomes import attributed_span

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import datetime

    from syncr_api.plans.records import BlockOutcomeRecord
    from syncr_domain.identifiers import AreaId
    from syncr_domain.intervals import Interval
    from syncr_domain.outcomes import RecordedOutcome
    from syncr_domain.plan import Block
    from syncr_domain.zones import Date


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewedDay:
    """One local date of a reviewed period, and what the log says about it.

    ``confirmed_at`` is the instant the day was settled, which is ``None`` for a day holding no
    block as well as for one nobody answered for. ``is_off_plan`` tells the two apart in the
    direction that matters: a day inside a declared off-plan period is not a day the user failed
    to answer for.
    """

    on: Date
    span: Interval
    blocks: tuple[Block, ...]
    confirmed_at: datetime | None
    is_off_plan: bool

    @property
    def is_confirmed(self) -> bool:
        """Whether this day contributes its minutes to the review.

        A day holding no block is neither confirmed nor unconfirmed, whatever instant sits on it:
        there is nothing to answer for. ``settled_at`` already answers ``None`` over an empty run of
        blocks, so a stored day cannot reach here otherwise; requiring the blocks HERE makes the
        rule structural rather than a property of one collaborator, which is what stops a week
        holding nothing from counting as a quarter's worth of evidence.
        """
        return bool(self.blocks) and self.confirmed_at is not None and not self.is_off_plan

    @property
    def is_unconfirmed(self) -> bool:
        """Whether this day holds blocks nobody has answered for."""
        return bool(self.blocks) and self.confirmed_at is None and not self.is_off_plan


@dataclass(frozen=True, slots=True)
class DayCounts:
    """How many of a period's days were confirmed, left unanswered, and declared away."""

    confirmed: int
    unconfirmed: int
    off_plan: int

    def __add__(self, other: DayCounts) -> DayCounts:
        """The counts of two periods together, so a quarter's are its weeks' own summed."""
        return DayCounts(
            confirmed=self.confirmed + other.confirmed,
            unconfirmed=self.unconfirmed + other.unconfirmed,
            off_plan=self.off_plan + other.off_plan,
        )


NO_DAYS = DayCounts(confirmed=0, unconfirmed=0, off_plan=0)


def is_covered_by(span: Interval, occupied: IntervalSet) -> bool:
    """Whether ``occupied`` leaves nothing of ``span`` uncovered.

    Emptiness of the residual rather than a comparison of minute counts. Both counts truncate a
    sub-minute remainder and they truncate independently, so a span whose own length carries
    seconds reads as the same number of minutes as the occupied time inside it while a fraction of
    it is still uncovered. This is `offplan.reading`'s own reasoning, applied per day.
    """
    return not IntervalSet([span]).subtract(occupied.clip(span))


def day_counts(days: Iterable[ReviewedDay]) -> DayCounts:
    """The three counts, taken over one pass so a day cannot land in two of them."""
    counted = NO_DAYS
    for day in days:
        counted += DayCounts(
            confirmed=int(day.is_confirmed),
            unconfirmed=int(day.is_unconfirmed),
            off_plan=int(day.is_off_plan),
        )
    return counted


def confirmed_coverage(
    days: Sequence[ReviewedDay],
    *,
    outcomes: Mapping[str, BlockOutcomeRecord],
    within: Interval,
    off_plan: IntervalSet,
) -> Mapping[AreaId, IntervalSet]:
    """The intervals each Area's blocks really occupied, over the confirmed days only.

    ``outcomes`` is keyed by the block id as a string, which is what a ``BlockId`` is: keying on
    the derived identity rather than on position is what lets one read of the log answer for every
    day of the period.

    Clipped to ``within`` and with ``off_plan`` removed. Both are needed and neither is redundant:
    a ``moved`` outcome carries a user-supplied interval that may reach outside the period
    altogether, and an off-plan span is out of the denominator, so a minute inside one is a minute
    no Area may be charged.
    """
    collected: dict[AreaId, list[Interval]] = {}
    for day in days:
        if not day.is_confirmed:
            continue
        for block in day.blocks:
            if block.area_id is None:
                continue
            attributed = attributed_span(block.interval, _recorded(outcomes.get(str(block.id))))
            if attributed is not None:
                collected.setdefault(block.area_id, []).append(attributed)
    return {
        area_id: IntervalSet(spans).clip(within).subtract(off_plan)
        for area_id, spans in collected.items()
    }


def claimed(covered: Mapping[AreaId, IntervalSet]) -> IntervalSet:
    """Every Area's coverage unioned, so a minute two Areas claim is claimed once.

    What tiles the denominator is this union plus the vacancy, never the sum of the per-Area
    figures. Two real blocks cannot occupy one minute, and nothing enforces that here: the union is
    what keeps the vacancy correct if one ever does.
    """
    unioned = IntervalSet()
    for spans in covered.values():
        unioned = unioned.union(spans)
    return unioned


def _recorded(found: BlockOutcomeRecord | None) -> RecordedOutcome | None:
    """The domain value the attribution table is stated over, or ``None`` for an absent row.

    An absent row IS ``presumed``, which the table already answers for, so nothing is fabricated
    here. This is the first production caller of ``as_domain``: the netting is stated over a domain
    value and the log hands back a record.
    """
    return None if found is None else found.as_domain()
