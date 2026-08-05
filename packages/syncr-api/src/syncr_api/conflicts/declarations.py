"""What a caller chose, as one value the service can read without touching a request body.

``anchor_type`` is a :class:`~syncr_api.core.patches.Patched` value rather than a plain optional,
because a retype has three cases and only two of them are expressible as one: apply this type, make
this commitment opaque busy time, or say nothing about a type at all. An omitted field and an
explicit null would otherwise be the same request, and clearing the type a commitment carries is a
destructive act to arrive at by leaving a field out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syncr_api.core.patches import Patched
    from syncr_api.plans.config import ConflictResolution
    from syncr_domain.identifiers import AnchorId


@dataclass(frozen=True, slots=True)
class ChosenResolution:
    """How the user answered one conflict, and the type they chose if they retyped."""

    resolution: ConflictResolution
    anchor_type: Patched[AnchorId | None]
