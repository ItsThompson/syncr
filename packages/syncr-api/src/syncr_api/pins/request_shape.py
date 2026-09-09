"""Resolve pin requests into a block placement and validate its shape."""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.core.errors import Conflict, NotFound, ValidationFailed
from syncr_api.core.errors import FieldError as WireFieldError
from syncr_api.pins.config import BLOCK_RESOURCE, START_FIELD
from syncr_api.plans.placements import constrains_a_solve
from syncr_domain.intervals import Interval

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_domain.identity import BlockId
    from syncr_domain.plan import Block, PlanDocument


def _block_of(document: PlanDocument, block_id: BlockId) -> Block:
    """The block this request names, or a 404 that says the plan does not hold one."""
    found = document.blocks_by_id().get(block_id)
    if found is None:
        raise NotFound(
            f"No {BLOCK_RESOURCE} in the plan for {document.iso_week} matches that identifier."
        )
    return found


def _starting_at(start: datetime, block: Block) -> Interval:
    """The placement a drag names: this block's own length, beginning where the request says.

    The length is the block's rather than the caller's, because a drag moves and does not resize.
    """
    return Interval(start, start + block.interval.duration)


def _require_a_placement_the_week_has_not_reached(
    block: Block, accepted: Interval, now: datetime
) -> None:
    """A placement the week has already reached is refused in both directions.

    The block having begun is a fact about the week: the moment has passed, so where that block ran
    is not a placement anybody has authority over, and the checker would refuse the move anyway.
    The requested start having gone is a fact about the request: nothing can be scheduled into time
    that no longer exists, so the field the caller sent is what the refusal names.
    """
    if not constrains_a_solve(block.interval, now):
        raise Conflict(
            f"{block.title} began at {block.interval.start.isoformat()}, and the past is not a "
            "placement this product may change. Nothing was moved: the block stays where it ran, "
            "and what happened in it is recorded on the day it belongs to."
        )
    if not constrains_a_solve(accepted, now):
        raise ValidationFailed(
            "That start has already passed, so nothing can be scheduled into it. Nothing was "
            "changed.",
            errors=[
                WireFieldError(
                    field=START_FIELD,
                    message="a pin names time the week has not reached yet",
                )
            ],
        )


def _require_a_placement_inside_the_week(accepted: Interval, span: Interval) -> None:
    """A pin binds ONE week, so a placement whose start falls outside that week's span is refused.

    The pin constrains the week it was made in and the next week's solve is unconstrained
    by it, so a placement starting outside the span would be a constraint on a week no row names.
    Checked against the assembled span rather than a span derived here, because a week's real length
    is a resolution of the zone profile: it is 167 or 169 hours across a daylight-saving transition
    and something else again across a travel boundary.

    The START is what decides ownership rather than the whole interval, because a Sunday-night frame
    occurrence starts inside the week and ends after it: its overhang into the next week is modelled
    by the assembler already, and refusing a pin at its own placement would make a block unpinnable.
    """
    if span.start <= accepted.start < span.end:
        return
    raise ValidationFailed(
        "That start puts the block outside the week it belongs to, and a pin binds one week. "
        "Nothing was changed: pin it inside this week, or pin the next week's own occurrence.",
        errors=[
            WireFieldError(
                field=START_FIELD, message="a pin names a placement inside the week it is made in"
            )
        ],
    )
