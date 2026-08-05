"""The wire shapes the two conflict routes read and answer with.

A conflict crosses the boundary as the pair a notice renders from: which commitment, which block,
and where the two meet. The binding travels with it, because a resolved conflict outlives the block
it names and the weekly session's repeated-collision item is stated over the identity rather than
over the digest.

``blockId`` is on the wire as well as the binding, because that is what the grid pairs a conflict
with a rendered block on. It is a digest of the week and the binding, so nothing on the client
composes one: it is read and compared.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - pydantic resolves annotations at runtime
from typing import TYPE_CHECKING
from uuid import UUID  # noqa: TC003 - pydantic resolves annotations at runtime

from pydantic import ConfigDict, Field

from syncr_api.conflicts.config import ANCHOR_TYPE_FIELD
from syncr_api.core.schemas import WireModel, WireSpan
from syncr_api.plans.config import CONFLICT_RESOLUTIONS, ConflictResolution
from syncr_api.plans.document_schemas import BindingResponse
from syncr_api.solving.schemas import OperationResponse

if TYPE_CHECKING:
    from syncr_api.conflicts.views import Resolved
    from syncr_api.plans.records import ConflictRecord

_RESOLUTIONS = ", ".join(f"`{resolution}`" for resolution in CONFLICT_RESOLUTIONS)


class ConflictResponse(WireModel):
    """One overlap nothing may resolve silently, and how it was answered if it has been."""

    id: UUID
    iso_week: str = Field(description="The week the overlap falls in, as `2026-W07`.")
    anchor_id: UUID = Field(
        description="The commitment the overlap is attributed to. For a prep or transit buffer "
        "landing on a pinned block this is the commitment that CAST the buffer, because the "
        "commitment is the fact that arrived and the buffer is its consequence."
    )
    block_id: str = Field(description="The block the commitment landed on, as the grid keys it.")
    binding: BindingResponse = Field(
        description="What the block holds. Travels with the conflict because the record outlives "
        "the block, and a repeated collision is computed over the identity."
    )
    overlap: WireSpan
    detected_at: datetime
    resolved_at: datetime | None = Field(
        default=None, description="Null while the conflict is still waiting for an answer."
    )
    resolution: ConflictResolution | None = Field(
        default=None, description=f"How it was answered: one of {_RESOLUTIONS}."
    )

    @classmethod
    def of(cls, record: ConflictRecord) -> ConflictResponse:
        """The wire shape of one stored conflict."""
        return cls(
            id=record.id,
            iso_week=str(record.iso_week),
            anchor_id=record.anchor_id,
            block_id=record.block_id,
            binding=BindingResponse.of(record.binding),
            overlap=WireSpan.of(record.overlap),
            detected_at=record.detected_at,
            resolved_at=record.resolved_at,
            resolution=record.resolution,
        )


class ConflictsResponse(WireModel):
    """Every conflict the query asked for, earliest overlap first."""

    conflicts: list[ConflictResponse]

    @classmethod
    def of(cls, records: tuple[ConflictRecord, ...]) -> ConflictsResponse:
        return cls(conflicts=[ConflictResponse.of(record) for record in records])


class ResolveConflictRequest(WireModel):
    """How the user answered, and the commitment type they chose if they retyped."""

    model_config = ConfigDict(extra="forbid")

    resolution: ConflictResolution = Field(
        description=f"One of {_RESOLUTIONS}. `kept-both` records the answer and leaves the "
        "overlap, and is the one answer that changes neither the plan nor what a solve reads."
    )
    anchor_type_id: UUID | None = Field(
        default=None,
        description="The commitment type to apply, or null to leave the commitment as opaque busy "
        f"time. Stated only with `retyped`; a `{ANCHOR_TYPE_FIELD}` sent with any other answer is "
        "refused rather than ignored.",
    )


class ResolvedConflictResponse(WireModel):
    """The answered conflict, and the solve that will read the answer.

    ``operation`` is null for `kept-both`, which asks for no solve: the overlap stays and the plan
    is unchanged, so there is nothing for a client to follow.
    """

    conflict: ConflictResponse
    operation: OperationResponse | None = None

    @classmethod
    def of(cls, resolved: Resolved) -> ResolvedConflictResponse:
        return cls(
            conflict=ConflictResponse.of(resolved.conflict),
            operation=(
                None if resolved.operation is None else OperationResponse.of(resolved.operation)
            ),
        )
