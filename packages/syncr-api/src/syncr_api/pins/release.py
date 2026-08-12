"""``StoredPinRelease``: the pin release a conflict resolution reaches through.

Section 07's resolution table says answering ``moved`` on a PINNED block removes the pin and
requests a solve, so the block is free to move, and that the removed pin's record is retained as
training data. The conflict path declares the seam and this is the pin feature's answer to it, which
is where the lifecycle question belongs: what a release does to the row is decided where pins are
written.

**A release deletes the row, and the record that persists is the edit event.** The record of a pin
persists permanently, and the resolution table says a released pin's record is retained; both are
true because the two are different objects. The row is the live constraint on this week's solve.
The ``edit_events`` row written in the same transaction as the pin is the fact about a week that
happened, and it carries the same pair, the same objective delta and the same weight-set version.
So a release loses nothing the learning layer reads.

The table could not express a released pin any other way. It holds no column for one, and adding one
would mean every reader of a pin filtering on it: the assembler, the promotion detector, and the
solver's own seeding. A deleted row is filtered by construction.

**Releasing a pin nothing holds is not an error.** A conflict is raised against the live plan and
answered later, so anything else may have released the pin in between; the resolution's other two
effects still have to happen.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_common.logging import get_logger

if TYPE_CHECKING:
    from syncr_api.plans.pins import PinRepository
    from syncr_domain.identity import BindingRef
    from syncr_domain.weeks import IsoWeek

_log = get_logger("syncr.pins")


class StoredPinRelease:
    """Releases the pin holding one binding in one week, over the table that holds it."""

    def __init__(self, pins: PinRepository) -> None:
        self._pins = pins

    async def release(self, iso_week: IsoWeek, binding: BindingRef) -> bool:
        """Free this content to be re-placed, reporting whether a pin was holding it."""
        released = await self._pins.release_binding(iso_week, binding)
        _log.info(
            "pins.pin.released_by_binding",
            iso_week=str(iso_week),
            binding_kind=binding.kind.value,
            entity_id=str(binding.entity_id),
            occurrence_key=binding.occurrence_key,
            was_pinned=released,
        )
        return released
