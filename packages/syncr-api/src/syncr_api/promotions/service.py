"""``PromotionService``: accept a repeated pin into the template, or decline it for an interval.

Two methods, one per route, and each is one decision plus one write.

**The accept MOVES the entry the pattern names, through the day-shape service rather than beside
it.** A block that materialized from a day shape carries that entry as its binding, so the candidate
already names the entry and the time; what is left is a change of target time, which is exactly
``TemplateService.change_entry``. Delegating means one write path, one invalidation rule, and one
log line for a template edit however it was asked for. A second write here would be a second place
the "which weeks does this reach" question is answered.

**Nothing is applied to the template except by an accept.** The read that raises a candidate writes
nothing at all, and a decline writes only its own row, so the template changes on exactly one
request.

**The decline stores the instant, not the pattern.** There is no candidate row to mark: detection is
one pass over pin rows and runs on every session read. What a decline records is the answer, keyed
by the candidate's own group, and the session drops a candidate whose group is still silenced.

**The accept does not re-run detection first.** It could: the pins are one bounded read away. It
would guard against a caller accepting a pattern that was never found, and that caller gains nothing
by it -- the same credential can move the same entry to the same time through the day-shape route,
which is the act this performs and the authority it requires. So the cost of two more reads on every
accept buys no authority the caller lacked, and the id is treated as what it is: the proposal,
quoted back.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from syncr_api.core.errors import Conflict
from syncr_api.core.patches import ABSENT
from syncr_api.core.principal import require_scope
from syncr_api.core.scopes import Scope
from syncr_api.promotions.absorption import accept_refusal
from syncr_api.promotions.config import DECLINE_SUPPRESSION_WEEKS
from syncr_api.templates.declarations import EntryChange
from syncr_common.logging import get_logger
from syncr_common.metrics import measured
from syncr_domain.snap import is_wall_time_on_snap_grid

if TYPE_CHECKING:
    from datetime import time

    from syncr_api.core.clock import Clock
    from syncr_api.core.principal import Principal
    from syncr_api.promotions.records import PromotionDeclineRecord
    from syncr_api.promotions.repository import PromotionDeclineRepository
    from syncr_api.templates.records import TemplateEntryRecord, TemplateRecord
    from syncr_api.templates.repository import TemplateRepository
    from syncr_api.templates.service import TemplateService
    from syncr_domain.promotion import PromotionRef

_log = get_logger("syncr.promotions")


@dataclass(frozen=True, slots=True, kw_only=True)
class AcceptedPromotion:
    """What one accept changed: the entry, which shape holds it, and where it was.

    ``shape_name`` and ``moved_from`` are here because the sentence a surface renders needs both and
    neither is on the entry: a reader is told which day shape changed and what the time used to be,
    so the edit is legible without opening Templates.
    """

    promotion_id: str
    entry: TemplateEntryRecord
    shape_name: str
    moved_from: time


class PromotionService:
    """One tenant's answer to a repeated pin: absorb it into the template, or silence it."""

    def __init__(
        self,
        *,
        shapes: TemplateRepository,
        templates: TemplateService,
        declines: PromotionDeclineRepository,
        clock: Clock,
    ) -> None:
        self._shapes = shapes
        self._templates = templates
        self._declines = declines
        self._clock = clock

    @measured("promotions")
    async def accept(self, principal: Principal, ref: PromotionRef) -> AcceptedPromotion:
        """Move the day-shape entry this pattern is about to the time it keeps being pinned to.

        The scope is checked before anything is read, and again by the day-shape service that
        performs the write: this is a template edit asked for another way, so it takes the authority
        a template edit takes and no other.
        """
        require_scope(principal, Scope.ADMIN)
        refusal = accept_refusal(ref)
        if refusal is not None:
            raise Conflict(refusal)
        shape, entry = await self._require_entry(ref)
        moved = await self._templates.change_entry(
            principal,
            shape.id,
            entry.id,
            EntryChange(
                target_time=_target_time(ref),
                duration_minutes=ABSENT,
                flex_band_minutes=ABSENT,
            ),
        )
        _log.info(
            "promotions.accepted",
            tenant_id=str(principal.tenant_id),
            promotion_id=ref.id,
            template_id=str(shape.id),
            entry_id=str(entry.id),
            from_target_time=entry.span.target_time.isoformat(),
            to_target_time=moved.span.target_time.isoformat(),
        )
        return AcceptedPromotion(
            promotion_id=ref.id,
            entry=moved,
            shape_name=shape.name,
            moved_from=entry.span.target_time,
        )

    @measured("promotions")
    async def decline(self, principal: Principal, ref: PromotionRef) -> PromotionDeclineRecord:
        """Record that this pattern was declined, and until when it is not raised again.

        Writing the instant rather than the interval is what makes the promise the reader was given
        the fact that is stored. A second decline of one pattern replaces the first: it is one
        answer given twice, and the row is keyed by the pattern rather than by the occasion.
        """
        require_scope(principal, Scope.PLAN_WRITE)
        at = self._clock()
        until = at + timedelta(weeks=DECLINE_SUPPRESSION_WEEKS)
        declined = await self._declines.decline(ref.id, at=at, until=until)
        _log.info(
            "promotions.declined",
            tenant_id=str(principal.tenant_id),
            promotion_id=ref.id,
            suppressed_until=until.isoformat(),
            suppression_weeks=DECLINE_SUPPRESSION_WEEKS,
        )
        return declined

    async def _require_entry(self, ref: PromotionRef) -> tuple[TemplateRecord, TemplateEntryRecord]:
        """The shape holding the entry this pattern names, and the entry.

        Read across every shape rather than by identifier, because a candidate names the ENTRY and
        not the shape that holds it: a tenant declares one shape per day type, so this is a handful
        of rows, and it is the same read the day-shape list route makes.
        """
        for shape in await self._shapes.list_all():
            for entry in shape.entries:
                if entry.id == ref.entity_id:
                    return shape, entry
        raise Conflict(
            "The day-shape entry this pattern is about is no longer declared, so there is nothing "
            "to move. It was removed after the pattern was found. Nothing was changed."
        )


def _target_time(ref: PromotionRef) -> time:
    """The wall time this pattern keeps landing on, as a day-shape entry declares one.

    The grid is checked HERE rather than left to ``EntrySpan``, and the reason is which failure a
    caller meets: the span's refusal is a 422 about a field of a request body, and this request has
    no body. An identifier naming a time off the grid is a conflict with what a template can hold.
    """
    if not is_wall_time_on_snap_grid(ref.wall_time):
        raise Conflict(
            f"A day-shape entry lands on a quarter hour and this pattern names {ref.local_time}, "
            "so no entry could hold it. Nothing was changed."
        )
    return ref.wall_time
