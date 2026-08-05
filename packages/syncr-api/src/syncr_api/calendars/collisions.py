"""What one sync pass needs from the plan side once a commitment has moved, declared here.

A commitment landing on a planned block is the one condition in this product that pushes a
notification, and it is detected when the commitment arrives rather than found later by a solve.
That ordering is what lets the notice name the block affected. Detecting it needs the live plan,
which is plan storage's, and the geometry a commitment casts, which is the anchor package's.
Neither is this package's dependency, so the requirement is declared here as a protocol and
answered by composition, exactly as the anchor reconciler's is.

**It is asked only after a pass that created or updated a commitment.** A feed that answered
"unchanged", a feed that could not be read, and a poll that found nothing new all leave the plan's
own occupancy exactly as it was, so there is nothing new to collide with. A removal frees space and
can raise nothing either.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime


class CollisionDetection(Protocol):
    """Raising the conflicts a tenant's live plans hold, as one sync pass needs it."""

    async def detect(self, *, now: datetime) -> object:
        """Raise every overlap the live plans in the horizon hold and are not already asked about.

        Called inside the pass's own transaction, so a tenant's anchors, its sync state and the
        conflicts they raised either all land or none of them do.

        Idempotent by construction: an overlap already waiting for an answer, or one the user
        answered by accepting it, is not raised again. What the return value carries is what was
        newly raised, and this pass does not read it: the caller of the pass reports counts, and
        the SSE push that tells the browser is the coordinator's.
        """
        ...
