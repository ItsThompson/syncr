"""The pin release a conflict resolution needs, declared where it is needed.

Removing the user's pin is what makes a pinned block movable, and it is the pin side of the
product's own lifecycle rather than the conflict side: which record survives a release, and what a
released pin still teaches the learning layer, are decided where pins are written. So this is a
protocol the resolution path declares and the pin feature answers, exactly as the week assembler
declares the seam that supplies it a week's placements.

``NoPins`` is the correct reading of this deployment rather than a placeholder for one. Nothing
writes a pin yet, so no stored document holds a pinned block either, and a resolution can only
reach the pinned branch through this seam in a test. What the seam buys is that the branch is the
production code path when a pin write exists, rather than something a later ticket has to add.
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
    """The pin release of a deployment where nothing writes a pin. Reads and writes nothing."""

    async def release(self, iso_week: IsoWeek, binding: BindingRef) -> bool:
        return False
