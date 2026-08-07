"""``extract``: one tenant's loaded rows to the observation lists the fitters read. Pure.

Testable with literals, which is the point: every rule about what counts is here, so a rule can be
driven by writing three rows in a test file rather than by seeding a database.

## The three exclusions, each unconditional

| Exclusion | Rule |
|---|---|
| Unconfirmed days | Excluded from every fitter. A day the user disengaged from is not perfect |
| Off-plan spans | Excluded WHOLESALE, whatever the confirmation state. No sample count grows |
| A corrected confirmation | Refitted from the corrected log, because the log is the truth |

The third is structural rather than a filter, and it is worth naming where a reader looks for it.
Nothing is carried between runs: a run reads the log from scratch and derives every observation from
it, so a corrected row produces a corrected observation on the next run with no invalidation step
and no cache for the correction to disagree with.

The off-plan exclusion is deliberately unconditional. A split rule preserving duration signal from
confirmed pinned blocks inside an off-plan span was considered and rejected: a holiday is a
different regime for WHEN you do things but arguably not for HOW LONG a gym session takes, and the
cost of the simple rule is a small amount of duration signal a few times a year.

## The two hours a block has, and which question each answers

A ``moved`` outcome happened somewhere other than where it was planned, so a lived block carries two
hours. The hour it REALLY happened in is what the fitness curve reads. The hour it was PLANNED in is
what the skip probability reads, because a skip probability answers "would the user refuse work put
here" and "here" is where the solver would be putting it.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING, Final

from syncr_domain.identity import block_id
from syncr_domain.outcomes import COMPLETION_STATES, MINUTES_STATE, OutcomeState
from syncr_domain.zones import resolve_zone
from syncr_learning.config import bucket_of
from syncr_learning.exclusions import is_off_plan
from syncr_learning.observations import (
    DurationObservation,
    Observations,
    SkipObservation,
    SwitchObservation,
    TimeOfDayObservation,
)
from syncr_learning.preferences import rank_examples
from syncr_learning.rearrangements import churn_observations

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from syncr_domain.identifiers import AreaId
    from syncr_domain.identity import BlockId
    from syncr_domain.intervals import Instant, Interval
    from syncr_domain.weeks import IsoWeek
    from syncr_learning.facts import (
        LoggedOutcome,
        OffPlanSpan,
        StoredRevision,
        TenantCorpus,
    )

MINUTES_AN_HOUR: Final = 60
MINUTES_A_DAY: Final = 24 * MINUTES_AN_HOUR
SECONDS_A_MINUTE: Final = 60

# The states that say the user did not do the work WHEN it was planned. `skipped` did not happen at
# all and `moved` happened elsewhere, and both are refusals of the slot the solver chose.
REFUSED_THE_SLOT: Final = frozenset({OutcomeState.SKIPPED, OutcomeState.MOVED})


def extract(corpus: TenantCorpus) -> Observations:
    """Every observation this tenant's rows support, with every exclusion already applied."""
    outcomes = {one.block_id: one for one in corpus.outcomes}
    lived = tuple(_lived_blocks(corpus.revisions, outcomes, corpus.off_plan))
    return Observations(
        durations=tuple(_durations(lived)),
        time_of_day=tuple(_time_of_day(lived)),
        skips=tuple(_skips(lived)),
        switches=tuple(_switches(lived)),
        churn=tuple(churn_observations(corpus.revisions, corpus.edits)),
        ranking=tuple(rank_examples(corpus.edits, corpus.off_plan)),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class LivedBlock:
    """One confirmed, on-plan block paired with what the user said about it.

    Internal to the extraction: it exists so the four block-derived observation kinds read one
    pairing rather than each redoing the join, the confirmation check and the off-plan check.
    """

    area_id: AreaId
    planned: Interval
    planned_hour: int
    happened_hour: int
    state: OutcomeState
    actual_minutes: int | None

    @property
    def went_well(self) -> bool:
        """Whether the content was done. Exactly one of the five states says it was not."""
        return self.state in COMPLETION_STATES

    @property
    def refused_the_slot(self) -> bool:
        """Whether the user did not do the work where the solver put it."""
        return self.state in REFUSED_THE_SLOT


def _lived_blocks(
    revisions: Sequence[StoredRevision],
    outcomes: Mapping[BlockId, LoggedOutcome],
    off_plan: Sequence[OffPlanSpan],
) -> Iterable[LivedBlock]:
    """Every block of every week's plan of record that a fitter may count, in span order per week.

    The plan of record is the LATEST revision of each week, because that is the arrangement the user
    lived: an earlier revision is a proposal the week moved past.

    A block with no outcome row is dropped rather than read as ``presumed``. The absence of a row is
    presumed-AND-unconfirmed, and an unconfirmed block is excluded by the first rule, so reading the
    absence as a completion would count a day the user never answered for.

    A block with no Area is dropped too. Every parameter fitted from a block is keyed on an Area,
    and the frame and the imported commitments carry none: neither competes for discretionary time.
    """
    for revision in plans_of_record(revisions):
        for block in sorted(revision.blocks, key=lambda one: one.interval.start):
            if block.area_id is None or is_off_plan(block.interval, off_plan):
                continue
            outcome = outcomes.get(block_id(revision.iso_week, block.binding))
            if outcome is None or not outcome.is_confirmed:
                continue
            happened = outcome.actual or block.interval
            yield LivedBlock(
                area_id=block.area_id,
                planned=block.interval,
                planned_hour=local_hour(block.interval.start, revision),
                happened_hour=local_hour(happened.start, revision),
                state=outcome.state,
                actual_minutes=outcome.actual_minutes,
            )


def plans_of_record(revisions: Sequence[StoredRevision]) -> list[StoredRevision]:
    """The latest revision of each week, in week order.

    Ordered so one corpus produces one observation sequence: a fitted mean is order-independent, and
    the switch fitter's adjacency is not.
    """
    latest: dict[IsoWeek, StoredRevision] = {}
    for revision in revisions:
        held = latest.get(revision.iso_week)
        if held is None or revision.created_at > held.created_at:
            latest[revision.iso_week] = revision
    return [latest[week] for week in sorted(latest)]


def local_hour(at: Instant, revision: StoredRevision) -> int:
    """The hour of the user's own day this instant fell in, in the zone the plan captured.

    A week's dates each carry their own zone, so a travelled Wednesday is a Wednesday in the zone
    the user was in. A revision with no captured profile falls back to the instant's own hour, which
    is UTC: that is a plan written before zones were captured, and it is stated rather than raising,
    because one such row must not stop a nightly run over a year of correct ones.
    """
    zones = revision.zone_by_date
    if not zones:
        return at.hour
    zone = zones.get(at.date()) or next(iter(zones.values()))
    return at.astimezone(resolve_zone(zone)).hour


def _durations(lived: Iterable[LivedBlock]) -> Iterable[DurationObservation]:
    """The estimate errors. One state carries the figure and the other four carry none."""
    for block in lived:
        if block.state is not MINUTES_STATE or block.actual_minutes is None:
            continue
        yield DurationObservation(
            area_id=block.area_id,
            planned_minutes=block.planned.total_minutes(),
            actual_minutes=block.actual_minutes,
        )


def _time_of_day(lived: Iterable[LivedBlock]) -> Iterable[TimeOfDayObservation]:
    """Whether the work went well, at the hour it really happened in."""
    for block in lived:
        yield TimeOfDayObservation(
            area_id=block.area_id, hour=block.happened_hour, went_well=block.went_well
        )


def _skips(lived: Iterable[LivedBlock]) -> Iterable[SkipObservation]:
    """Whether the user refused the slot, in the part of the day it was PLANNED for."""
    for block in lived:
        yield SkipObservation(
            area_id=block.area_id,
            bucket=bucket_of(block.planned_hour),
            was_refused=block.refused_the_slot,
        )


def _switches(lived: Sequence[LivedBlock]) -> Iterable[SwitchObservation]:
    """The room this user really left between adjacent blocks, split by whether the Area changed.

    Adjacency is over the blocks that carry an Area, in span order, which is the set the objective's
    own context-switch term walks.

    A pair whose gap is longer than a day is dropped. A night's sleep leaves hours of room and would
    swamp the difference the price is measured as, which is the same reading the solver's term takes
    when it says a gap that long absorbs any price. A pair that overlaps is dropped for the opposite
    reason: a negative gap is not room the week left.
    """
    for first, second in pairwise(lived):
        elapsed = second.planned.start - first.planned.end
        minutes = int(elapsed.total_seconds() // SECONDS_A_MINUTE)
        if minutes < 0 or minutes > MINUTES_A_DAY:
            continue
        yield SwitchObservation(gap_minutes=minutes, changed_area=first.area_id != second.area_id)
