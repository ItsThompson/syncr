"""Which block a conflict names, and who can move it. The whole of what a resolution acts on.

"Move the block" means something different depending on what fixed the block's time, and stating
those cases is what removes the ambiguity a single phrase left. There are exactly three answers,
and each is a different act:

| The block | Who can move it | What ``moved`` does |
|---|---|---|
| an unpinned habit or task the solver placed | the solver | request a solve. The commitment
  is hard occupancy now, so the solver cannot put it back |
| a block the user pinned | the user | remove the pin, then request a solve, so the block is
  free to move |
| a block a declaration or an anchor's geometry fixes | nobody | **nothing.** syncr does not
  choose between the two ways to change what fixed it |

The third row is the one the resolution table states for a materialized template entry, and it
holds for every block whose time a declaration decides: a concrete template entry, a routine of the
circadian frame, and a prep or transit buffer, which cannot move at all because it is measured from
its commitment's own time. A collision raises a conflict rather than displacing such a block, so
something has to decide whether this week is an exception or the shape was wrong, and that
something is the user.

**A block the live plan no longer holds is the solver's.** A later revision already dropped or
relocated it, so there is no pin to remove and nothing to refuse: a solve is the only act left, and
it will not put anything back into the commitment's own time.

## Why the pin is checked before the origin

A user may pin a derived buffer elsewhere, which is how a longer-than-usual commute is expressed,
and a pinned template entry is a one-off exception to a declared shape. In both cases the pin is
what put the block where it is, so removing the pin is what moves it, whatever the origin says
about where it would otherwise have gone.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from syncr_domain.identity import Origin

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_domain.identity import BlockId
    from syncr_domain.plan import Block, PlanDocument


class Movability(StrEnum):
    """Who can move the block a conflict names."""

    THE_SOLVER = "the_solver"
    THE_USER = "the_user"
    NOBODY = "nobody"


# Who decides where a block of each origin goes. Read twice, so its completeness is not a claim
# beside it: a test asserts every member of the vocabulary is a key, because a hand-kept set going
# stale would otherwise surface as a `KeyError` on a request rather than as a red test.
#
# `Movability.THE_USER` is deliberately not a value here. A pin is what put the block where it is,
# whatever the origin says about where it would otherwise have gone, so the pin is read first.
#
# An imported commitment is a key for completeness rather than because a conflict can name one: the
# detector never raises a conflict against an anchor block, because two genuine commitments
# overlapping is not something the product owns either.
MOVABILITY_BY_ORIGIN: Final[Mapping[Origin, Movability]] = {
    Origin.HABIT: Movability.THE_SOLVER,
    Origin.TASK: Movability.THE_SOLVER,
    Origin.FRAME: Movability.NOBODY,
    Origin.TEMPLATE_ENTRY: Movability.NOBODY,
    Origin.PREP: Movability.NOBODY,
    Origin.TRANSIT: Movability.NOBODY,
    Origin.ANCHOR: Movability.NOBODY,
}


@dataclass(frozen=True, slots=True)
class Overlapped:
    """The block a conflict was raised against, as the live plan holds it now.

    ``block`` is ``None`` when the live plan no longer holds it, which is a normal state rather
    than an error: a conflict is retained and the plan moves on.
    """

    block: Block | None
    movable_by: Movability

    @property
    def origin(self) -> Origin | None:
        """What the block is, for a refusal that has to say what fixed its time."""
        return None if self.block is None else self.block.origin


def overlapped_block(live: PlanDocument | None, block_id: BlockId) -> Overlapped:
    """The block ``block_id`` names in ``live``, and who can move it.

    A pure function of the document and the id, because the id is a digest of the week and the
    binding: pairing needs no lookup and no clock.
    """
    held = None if live is None else live.blocks_by_id().get(block_id)
    if held is None:
        return Overlapped(block=None, movable_by=Movability.THE_SOLVER)
    if held.pinned:
        return Overlapped(block=held, movable_by=Movability.THE_USER)
    return Overlapped(block=held, movable_by=MOVABILITY_BY_ORIGIN[held.origin])
