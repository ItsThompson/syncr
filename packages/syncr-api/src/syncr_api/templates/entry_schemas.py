"""The wire shapes one entry of a day shape is declared, changed, and read in.

**An entry to declare is one of two shapes, discriminated by ``kind``.** A concrete entry names a
binding and a slot names an Area, and neither can express the other's fields at all: the union is
what makes the pairing rule structural, so a form cannot offer a submit that will fail. Each
request carries a ``declaration()`` rather than being read field by field at the route, which is
what keeps the two kinds from becoming a branch at the call site.

**No shape here can carry a cadence.** Every request forbids unknown fields, so a body naming
``cadence``, ``frequency``, or ``repeat`` is a stated 422 rather than a value quietly dropped.
Cadence lives on a habit: a template says what a day looks like, not how often something happens.

**A response is flat where a request is a union.** A response asserts nothing, so it states the
kind and leaves the fields the other kind does not use as null. The union exists to make an
inconsistent declaration unrepresentable, which is a property only a request needs.

The span's bounds are the domain's own constants, so the document advertises exactly what the span
accepts. The grid rule is not expressible as a bound and is checked by the span itself, which is
why every request here builds one.
"""

from __future__ import annotations

from datetime import time  # noqa: TC003 - pydantic resolves annotations at runtime
from typing import TYPE_CHECKING, Literal, Self
from uuid import UUID  # noqa: TC003 - pydantic resolves annotations at runtime

from pydantic import ConfigDict, Field, field_validator

from syncr_api.core.schemas import WireModel
from syncr_api.plans.entry_content import THE_FRAME_PLACES_A_ROUTINE
from syncr_api.templates.declarations import ConcreteEntry, SlotEntry
from syncr_domain.snap import SNAP_MINUTES
from syncr_domain.templates import (
    MAX_DURATION_MINUTES,
    MAX_FLEX_BAND_MINUTES,
    MIN_DURATION_MINUTES,
    BindingTarget,
    EntrySpan,
    TemplateEntryKind,
)

if TYPE_CHECKING:
    from syncr_api.templates.records import TemplateEntryRecord

TARGET_TIME_DESCRIPTION = (
    "Wall time, no zone: 07:00 means 07:00 wherever the user is, resolved against the zone "
    f"active on the date it materializes for. Lands on a {SNAP_MINUTES}-minute step of the "
    "grid, because the entry is fixed by derivation and nothing moves it onto the grid later."
)
DURATION_DESCRIPTION = (
    f"How long the entry runs, in minutes: {MIN_DURATION_MINUTES} to {MAX_DURATION_MINUTES}, "
    f"in whole {SNAP_MINUTES}-minute steps so the block it materializes ends on the grid."
)
FLEX_BAND_DESCRIPTION = (
    "How far a placement may SHIFT the entry either way, in minutes, up to "
    f"{MAX_FLEX_BAND_MINUTES}. It never shrinks it: the shape declares the span. A band below "
    f"{SNAP_MINUTES} permits no shift, because every placement lands on the grid."
)
AREA_ON_A_SLOT_DESCRIPTION = (
    "The Area this slot reserves time for. The solver binds a task or a habit occurrence in "
    "that Area at solve time, and the bound content's own name is what appears on the block."
)
BINDING_TARGET_DESCRIPTION = (
    "Which table bindingRef names. A routine and a habit are separate tables, so the "
    "identifier alone does not say which to read."
)
PLACEMENT_STATEMENT_DESCRIPTION = (
    "What places this entry, or null when its own declaration does. Present on an entry naming a "
    "routine, because the frame places that routine and the entry's own time places nothing: a "
    "declaration nothing materializes is stated rather than silently ignored. Named for its "
    "subject rather than `statement`, because a response that nests an entry carries a statement "
    "of its own about a different thing."
)

_NOT_NULLABLE_MESSAGE = (
    "this field cannot be cleared, so null is refused rather than read as no change. "
    "Leave it out to keep the stored value."
)


class TemplateEntryResponse(WireModel):
    """One part of a day shape.

    It carries no pin field and no glyph, because a template entry is fixed by DERIVATION rather
    than pinned: its time comes from the shape, so the solver may not move it, no ``Pin`` row
    exists for it, and it is not a training label. Fixed by derivation is not "never moved": an
    anchor landing on a materialized entry raises a conflict, and the user may still move one by
    editing this shape or by pinning that single occurrence.
    """

    id: UUID
    kind: TemplateEntryKind
    target_time: time = Field(description=TARGET_TIME_DESCRIPTION)
    duration_minutes: int = Field(description=DURATION_DESCRIPTION)
    flex_band_minutes: int = Field(description=FLEX_BAND_DESCRIPTION)
    area_id: UUID | None = Field(description=AREA_ON_A_SLOT_DESCRIPTION)
    binding_target: BindingTarget | None = Field(description=BINDING_TARGET_DESCRIPTION)
    binding_ref: UUID | None = Field(
        description="The routine or habit a concrete entry names. Null on a slot, which binds "
        "its content at solve time."
    )
    placement_statement: str | None = Field(
        default=None, description=PLACEMENT_STATEMENT_DESCRIPTION
    )

    @classmethod
    def of(cls, record: TemplateEntryRecord) -> Self:
        """A stored entry as this shape. On the schema so the two routes that answer with an
        entry -- this package's, and the promotion accept that moves one -- map it one way.

        The statement is the charge rule's own sentence, imported from where the charge is decided,
        so the words the author reads and the rule the assembly applies cannot drift apart.
        """
        return cls(
            id=record.id,
            kind=record.kind,
            target_time=record.span.target_time,
            duration_minutes=record.span.duration_minutes,
            flex_band_minutes=record.span.flex_band_minutes,
            area_id=record.area_id,
            binding_target=record.binding_target,
            binding_ref=record.binding_ref,
            placement_statement=(
                THE_FRAME_PLACES_A_ROUTINE
                if record.binding_target is BindingTarget.ROUTINE
                else None
            ),
        )


class _EntrySpanFields(WireModel):
    """The three fields both kinds of entry declare."""

    model_config = ConfigDict(extra="forbid")

    target_time: time = Field(description=TARGET_TIME_DESCRIPTION)
    duration_minutes: int = Field(
        ge=MIN_DURATION_MINUTES, le=MAX_DURATION_MINUTES, description=DURATION_DESCRIPTION
    )
    flex_band_minutes: int = Field(
        default=0, ge=0, le=MAX_FLEX_BAND_MINUTES, description=FLEX_BAND_DESCRIPTION
    )

    def span(self) -> EntrySpan:
        """The domain span this request declares, which is where the grid rule is applied."""
        return EntrySpan(
            target_time=self.target_time,
            duration_minutes=self.duration_minutes,
            flex_band_minutes=self.flex_band_minutes,
        )


class ConcreteEntryRequest(_EntrySpanFields):
    """A specific routine or habit at a target time. It cannot omit its binding."""

    kind: Literal[TemplateEntryKind.CONCRETE]
    binding_target: BindingTarget = Field(description=BINDING_TARGET_DESCRIPTION)
    binding_ref: UUID = Field(description="The routine or habit this entry names.")
    area_id: UUID | None = Field(
        default=None,
        description="Optional, and a statement about reporting rather than about content: the "
        "routine or habit this entry names already says what happens. On an entry naming a "
        "routine it reports nothing at all: the frame places that routine and its minutes "
        "belong to the frame.",
    )

    def declaration(self) -> ConcreteEntry:
        """What the service applies. Polymorphic, so the route has no kind to branch on."""
        return ConcreteEntry(
            span=self.span(),
            binding_target=self.binding_target,
            binding_ref=self.binding_ref,
            area_id=self.area_id,
        )


class SlotEntryRequest(_EntrySpanFields):
    """An Area and a duration, with the content bound at solve time.

    It has nowhere to put a binding: ``bindingRef`` is not a member and an unknown field is
    rejected, so a slot claiming specific content is a stated 422.
    """

    kind: Literal[TemplateEntryKind.SLOT]
    area_id: UUID = Field(description=AREA_ON_A_SLOT_DESCRIPTION)

    def declaration(self) -> SlotEntry:
        """What the service applies. Polymorphic, so the route has no kind to branch on."""
        return SlotEntry(span=self.span(), area_id=self.area_id)


class EntryPatchRequest(WireModel):
    """A partial update to an entry's span. An omitted field is left alone.

    The kind, the binding, and the Area are not members of this shape and an unknown field is
    rejected. A materialized entry's identity is the entry itself, keyed by its identifier and
    the local date, so rebinding one in place would leave stored outcomes, pins, and edit events
    attributing one identity to content it no longer holds. Remove the entry and declare another.
    """

    model_config = ConfigDict(extra="forbid")

    target_time: time | None = Field(default=None, description=TARGET_TIME_DESCRIPTION)
    duration_minutes: int | None = Field(
        default=None,
        ge=MIN_DURATION_MINUTES,
        le=MAX_DURATION_MINUTES,
        description=DURATION_DESCRIPTION,
    )
    flex_band_minutes: int | None = Field(
        default=None, ge=0, le=MAX_FLEX_BAND_MINUTES, description=FLEX_BAND_DESCRIPTION
    )

    @field_validator("target_time", "duration_minutes", "flex_band_minutes")
    @classmethod
    def _refuse_an_explicit_null(cls, value: object) -> object:
        """Refuse ``null`` on the three fields that have nothing to clear.

        A validator runs only for a field the request actually named, so an omitted field is
        untouched by this and an explicit null is a stated 422. Without it, both would arrive as
        ``None`` and the two intentions would be indistinguishable.
        """
        if value is None:
            raise ValueError(_NOT_NULLABLE_MESSAGE)
        return value
