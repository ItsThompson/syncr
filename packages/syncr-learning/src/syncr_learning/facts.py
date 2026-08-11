"""What the job loaded: one value per row, in the shape the pure layer reads.

These are the boundary between the storage adapter and everything above it. The adapter's job is to
produce them; nothing above it knows a table, a column or a JSONB key exists.

**Every rule about what counts is stated over these rather than in SQL.** A confirmed day, an
off-plan span and a corrected confirmation each decide what a fitter may count, and each is a rule
the Learned screen explains in one sentence. Stated in a ``WHERE`` clause they would be untestable
with literals and invisible to a reader of the fitters; stated over these values they are
:mod:`syncr_learning.features`, which takes lists and returns lists.

So a value here carries what the row said, INCLUDING the part a rule will refuse it for. An outcome
that was never confirmed reaches the extractor and is dropped there, which is why it has an
``is_confirmed`` field rather than being absent.

**The projections are narrow on purpose.** A stored plan document holds a week: blocks, forbidden
windows, empty slots, reason records, adjustments. Three of its fields are what any fitter reads, so
that is what :class:`PlannedBlock` and :class:`StoredRevision` carry. Rebuilding the whole document
would mean restating the whole of the api's document spelling in a package that must not import it.

**A pin is the one projection this module does not declare.** ``syncr_domain.promotion`` holds
``PinPlacement``, the shape the rule that reads pins is stated over, and the api's weekly session is
that rule's one reader. So the value belongs to the domain rather than here, and a second
declaration would be a second spelling of one fact.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_domain.identifiers import AreaId, TenantId
    from syncr_domain.identity import BindingRef, BlockId
    from syncr_domain.intervals import Instant, Interval
    from syncr_domain.outcomes import OutcomeState
    from syncr_domain.promotion import PinPlacement
    from syncr_domain.weeks import IsoWeek
    from syncr_domain.zones import Date, ZoneId


@dataclass(frozen=True, slots=True, kw_only=True)
class PlannedBlock:
    """One block of one stored revision: what it is, when it was planned, and what it charges."""

    binding: BindingRef
    interval: Interval
    area_id: AreaId | None


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredRevision:
    """One revision of one week's plan, reduced to the three things a fitter reads.

    ``zone_by_date`` is the profile the plan was COMPUTED with rather than the tenant's zone today.
    A fitness curve is keyed on the hour of the user's own day, and a week lived in another zone was
    lived at that zone's hours; re-resolving it against today's home zone would move every hour of a
    travelled week.
    """

    iso_week: IsoWeek
    created_at: Instant
    zone_by_date: Mapping[Date, ZoneId]
    blocks: tuple[PlannedBlock, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class LoggedOutcome:
    """What the user said happened to one block, keyed by the block id the log stores.

    ``is_confirmed`` is the whole of the unconfirmed-day exclusion as a fact: the column it comes
    from is ``confirmed_at``, and a row without one is a day the user disengaged from.
    """

    block_id: BlockId
    state: OutcomeState
    actual_minutes: int | None
    actual: Interval | None
    is_confirmed: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class RecordedEdit:
    """One pairwise preference, as its edit-event row states it.

    ``measurement_delta`` is ``None`` for every event written before the difference was measured.
    Those rows are the corpus and E5 forbids pruning them, so the weight fit excludes them and
    counts what it excluded, rather than reading an absent vector as a zero one.
    """

    iso_week: IsoWeek
    created_at: Instant
    proposed: Interval
    accepted: Interval
    objective_delta: float
    measurement_delta: Mapping[str, float] | None
    weight_set_version: int
    inside_off_plan: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class OffPlanSpan:
    """One declared span of time off, as the exclusion reads it. Its two ends and nothing else."""

    interval: Interval


@dataclass(frozen=True, slots=True, kw_only=True)
class TenantCorpus:
    """Everything one tenant's run reads, loaded once.

    One value rather than five arguments, because a run is "load, then fit": every fitter reads part
    of this and none of it reads a database, so a corpus is what makes a run reproducible from a
    snapshot and what makes the idempotence claim checkable without a clock.
    """

    tenant_id: TenantId
    revisions: tuple[StoredRevision, ...]
    outcomes: tuple[LoggedOutcome, ...]
    edits: tuple[RecordedEdit, ...]
    pins: tuple[PinPlacement, ...]
    off_plan: tuple[OffPlanSpan, ...]
