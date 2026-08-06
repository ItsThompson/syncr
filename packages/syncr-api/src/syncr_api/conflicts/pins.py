"""The pin release a conflict resolution needs, declared where it is needed.

Removing the user's pin is what makes a pinned block movable, and it is the pin side of the
product's own lifecycle rather than the conflict side: which record survives a release, and what a
released pin still teaches the learning layer, are decided where pins are written. So this is a
protocol the resolution path declares and the pin feature answers, exactly as the week assembler
declares the seam that supplies it a week's placements.

``NoPins`` is kept for the ONE suite that still needs it: the resolution suite drives the pinned
branch against a recording fake, and the null implementation is what its "no pin was holding it"
case is stated over. Production wires :class:`syncr_api.pins.release.StoredPinRelease`, which
deletes the row and leaves the edit event that outlives it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syncr_domain.identity import BindingRef
    from syncr_domain.weeks import IsoWeek


class PinRelease(Protocol):
    """Releasing the user's pin on one binding for one week."""

    async def release(self, iso_week: IsoWeek, binding: BindingRef) -> bool:
        """Free this content to be re-placed, reporting whether a pin was holding it.

        The RECORD of the pin is retained whatever this does: it is a fact about a week and a
        training label, and what it stops being is a constraint on the next solve.

        A binding with no pin is not an error. A conflict is raised against the live plan, and the
        pin holding a block may have been released by anything else since.
        """
        ...


class NoPins:
    """A pin release that releases nothing. Reads and writes nothing."""

    async def release(self, iso_week: IsoWeek, binding: BindingRef) -> bool:
        return False
