"""The body a guarded removal stores, so a retried removal replays rather than 404ing.

The guard stores and replays a response MODEL, and a route answering ``204`` has no other shape to
store. Without one, a retry under the same key re-runs the removal and finds the row already gone,
so a caller that resends a request it never saw the answer to is told the thing it just removed
does not exist.

It never reaches the wire: a guarded removal declares ``response_class=Response`` and builds its own
empty ``204``, because a returned ``None`` is still serialized.

It lives beside the guard rather than in a feature module because what it satisfies is the guard's
storage contract rather than any one resource's wire shape, so every guarded removal answers with
this one shape. What separates two removals' claims is the route key each handler passes.
"""

from __future__ import annotations

from typing import Literal

from syncr_api.core.schemas import WireModel


class Removed(WireModel):
    """What a guarded removal answers with, so a retry under one key replays instead of 404ing."""

    removed: Literal[True] = True
