"""The wire shape of a stored plan document: the blocks a week holds, and the two kinds of gap.

The Week screen's whole read is one request, so a block arrives with the reason that explains it
rather than behind a second call per block. The six clause shapes are ``clause_schemas.py``.

**Every field is required and the nullable ones are nullable.** A field with a default is OPTIONAL
in the generated document, so a client would have to narrow ``undefined`` as well as ``null`` on a
key the server always sends.

**Three of the document's own fields are deliberately absent**, and they are the three minute
figures: ``discretionary_minutes``, ``unallocated_minutes``, and ``oversubscription_minutes``. Each
was computed against the inputs the solve read, so a period declared off-plan afterwards moves the
real figure and not the stored one. The week view carries all three as ``readings``, live, from the
arithmetic the budget report divides, which is what stops one payload from spelling one figure
twice and disagreeing with itself.

**A block's identity, its origin, and its chunk number are derived, and they are still on the
wire.** None has a field on the domain value, because a stored id is a cache of a hash and an
origin is a second reading of a binding kind. On the wire they are what a client pairs a selection,
a drag, and an outcome on, so they are rendered from the derivation rather than asking every client
to repeat it.

**An empty slot names an Area, and what that Area is CALLED is not in the document.** A name is the
user's own word for a row they may rename, and a stored week is a fact about that week, so the name
is resolved here against the Areas this response was read with. ``slot_contexts.py`` holds that
resolution and the refusal it raises when the two do not cover each other.

**An empty slot's gutter wording is RENDERED here, and its reason travels beside it.** One wording
per reason is :mod:`syncr_domain.gaps`'s single statement of it. That module is Python and the
clients that draw a gap are not, so a client composing the words from the reason code would be the
second statement that rule exists to forbid. The reason stays on the wire because it is what a
client branches on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self
from uuid import UUID  # noqa: TC003 - pydantic resolves annotations at runtime

from pydantic import Field

from syncr_api.core.schemas import WireModel, WireSpan
from syncr_api.plans.clause_schemas import ReasonResponse
from syncr_api.plans.slot_contexts import slot_context

# Runtime imports: each is a closed vocabulary a response field is annotated with, and pydantic
# resolves those annotations while the app is being built.
from syncr_domain.gaps import EmptySlotReason, ForbiddenKind, ForbiddenScope  # noqa: TC001
from syncr_domain.identity import BindingKind, Origin  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_api.plans.anchor_origins import AnchorOrigin
    from syncr_domain.gaps import EmptySlot, ForbiddenWindow, SlotContext
    from syncr_domain.identifiers import AreaId
    from syncr_domain.identity import BindingRef
    from syncr_domain.plan import Block, PlanDocument


class BindingResponse(WireModel):
    """What a block's content IS: the identity six mechanisms pair on."""

    kind: BindingKind
    entity_id: UUID = Field(description="The row this block's content comes from.")
    occurrence_key: str = Field(
        description="Which occurrence of that row: a date, a zero-padded index, or a transit leg."
    )
    split_index: int | None = Field(
        description="Which chunk of a divided task this is. Null when it is whole."
    )

    @classmethod
    def of(cls, binding: BindingRef) -> Self:
        return cls(
            kind=binding.kind,
            entity_id=binding.entity_id,
            occurrence_key=binding.occurrence_key,
            split_index=binding.split_index,
        )


class AnchorOriginResponse(WireModel):
    """The feed one imported commitment came from, and whether that feed is failing now."""

    source_id: UUID = Field(
        description="The calendar source this commitment was read from. On the block itself, so "
        "marking what a failing feed touched costs no second read."
    )
    possibly_stale: bool = Field(
        description="Whether that source has been failing long enough to doubt what it fed, "
        "decided here against the server's own threshold, which never crosses the wire. A block "
        "that is not bound to an import answers null on anchorOrigin instead of an answer."
    )

    @classmethod
    def of(cls, origin: AnchorOrigin) -> Self:
        return cls(source_id=origin.source_id, possibly_stale=origin.possibly_stale)


class BlockResponse(WireModel):
    """One thing that happens in the week, and why it is where it is."""

    id: str = Field(
        description="A hash of the week and the binding, derived on read, so it is stable across "
        "reads and cannot name content it does not hold."
    )
    interval: WireSpan
    binding: BindingResponse
    origin: Origin = Field(description="What this block is to the reader, read from the binding.")
    title: str
    reason: ReasonResponse
    area_id: UUID | None = Field(
        description="The Area this block is charged to. Null for the frame and for an imported "
        "anchor: one defines how much time exists and the other is time the product does not own.",
    )
    pinned: bool = Field(
        description="True only for the user's own edit. A block whose time was fixed by "
        "derivation is not pinned and carries no pin glyph, even where the solver cannot move it."
    )
    superseded_placement: WireSpan | None = Field(
        description="Where a pinned block would otherwise have been."
    )
    objective_delta: float | None = Field(description="What overriding that placement cost.")
    split_count: int | None = Field(description="How many chunks the divided task was split into.")
    anchor_origin: AnchorOriginResponse | None = Field(
        description="The calendar feed this block's imported commitment came from, and whether "
        "that feed is failing now. Null for every block no import binds: a solver-placed or "
        "frame block claims nothing about any feed."
    )

    @classmethod
    def of(cls, block: Block, origin: AnchorOrigin | None) -> Self:
        return cls(
            id=block.id,
            interval=WireSpan.of(block.interval),
            binding=BindingResponse.of(block.binding),
            origin=block.origin,
            title=block.title,
            reason=ReasonResponse.of(block.reason),
            area_id=block.area_id,
            pinned=block.pinned,
            superseded_placement=(
                None
                if block.superseded_placement is None
                else WireSpan.of(block.superseded_placement)
            ),
            objective_delta=block.objective_delta,
            split_count=block.split_count,
            anchor_origin=None if origin is None else AnchorOriginResponse.of(origin),
        )


class ForbiddenWindowResponse(WireModel):
    """A span work is forbidden in, and what forbade it."""

    interval: WireSpan
    kind: ForbiddenKind
    scope: ForbiddenScope = Field(
        description="Whether the window forbids every Area, or only the ones it names."
    )
    forbidden_area_ids: list[UUID]
    label: str
    anchor_id: UUID = Field(description="The commitment whose type cast this window.")

    @classmethod
    def of(cls, window: ForbiddenWindow) -> Self:
        return cls(
            interval=WireSpan.of(window.interval),
            kind=window.kind,
            scope=window.scope,
            forbidden_area_ids=list(window.forbidden_area_ids),
            label=window.label,
            anchor_id=window.anchor_id,
        )


class EmptySlotResponse(WireModel):
    """Discretionary time an Area was offered, and nothing filled."""

    interval: WireSpan
    area_id: UUID
    reason: EmptySlotReason = Field(description="Why the slot holds nothing.")
    label: str = Field(
        description="The one wording this reason renders beside the slot, with the Area's own name "
        "substituted where it names one. Rendered here rather than by the client, because the "
        "wordings have one home and it is not reachable from one."
    )

    @classmethod
    def of(cls, slot: EmptySlot, context: SlotContext) -> Self:
        """One empty slot on the wire, and the wording a gutter states it in.

        ``context`` carries what the slot itself cannot: the name of the Area it is charged to,
        which :func:`syncr_domain.gaps.gutter_label` substitutes into the wordings that name one.
        It is resolved per slot by the caller, from one read, rather than looked up here.
        """
        return cls(
            interval=WireSpan.of(slot.interval),
            area_id=slot.area_id,
            reason=slot.reason,
            label=slot.gutter_label(context),
        )


class PlanDocumentResponse(WireModel):
    """One week's plan, in full, as the grid renders it."""

    iso_week: str
    zone_by_date: dict[str, str] = Field(
        description="The active zone per day, captured when the plan was produced, so a travel "
        "override declared afterwards cannot silently re-read a stored week. All seven dates, "
        "keyed by ISO date."
    )
    blocks: list[BlockResponse]
    forbidden_windows: list[ForbiddenWindowResponse]
    empty_slots: list[EmptySlotResponse]
    adjustments: list[UUID] = Field(
        description="The approved concessions this plan was solved under, so a week never looks "
        "feasible for a reason the user cannot see."
    )

    @classmethod
    def of(
        cls,
        document: PlanDocument,
        *,
        area_names: Mapping[AreaId, str],
        anchor_origins: Mapping[UUID, AnchorOrigin],
    ) -> Self:
        """The wire shape of one rebuilt document, in the order the domain holds it.

        The zone mapping is emitted in date order rather than in the order the document's keys
        happened to arrive, so two reads of one week are byte-identical.

        ``area_names`` names every Area this tenant holds, and each empty slot resolves its own
        against it: one read of the rows answers every gap in the week, and a slot charged to an
        Area the mapping does not name is refused rather than answered.

        ``anchor_origins`` names the feed behind each imported commitment, keyed by anchor. A week
        composed without the two reads that answer it passes an empty mapping, and every block
        then answers null rather than a claim nothing read.
        """
        return cls(
            iso_week=str(document.iso_week),
            zone_by_date={
                day.isoformat(): zone for day, zone in sorted(document.zone_by_date.items())
            },
            blocks=[
                BlockResponse.of(block, anchor_origins.get(block.binding.entity_id))
                for block in document.blocks
            ],
            forbidden_windows=[
                ForbiddenWindowResponse.of(window) for window in document.forbidden_windows
            ],
            empty_slots=[
                EmptySlotResponse.of(slot, slot_context(slot, area_names))
                for slot in document.empty_slots
            ],
            adjustments=list(document.adjustments),
        )
