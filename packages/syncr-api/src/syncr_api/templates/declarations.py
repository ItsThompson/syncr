"""What a request asked to declare or change, as the service takes it.

These sit between the route that read the request and the service that applies it, so the
service never imports a wire schema and the route never decides anything.

**The two kinds of entry are two types, not one type with a mode.** A concrete entry cannot be
built without a binding and a slot has nowhere to put one, so the pairing rule holds by
construction rather than by a check somewhere that a later caller might skip. What the two share
is a span, which is why the span is one field rather than three repeated per kind.

**An entry's content is declared once.** :class:`EntryChange` carries the span's three fields
and nothing else: no kind, no binding, no Area. A materialized entry's identity is the ENTRY,
keyed by its identifier and the local date, so rebinding one in place would leave stored
outcomes, pins, and edit events attributing one identity to content it no longer holds.
Changing what an entry holds is therefore removing it and declaring another.

Each field of a change is two-valued rather than three: absent leaves the stored value alone,
and a value replaces it. Nothing in a span is nullable, so there is nothing an explicit null
could clear.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from syncr_api.core.patches import resolved
from syncr_domain.templates import EntrySpan, TemplateEntryKind

if TYPE_CHECKING:
    from datetime import time
    from uuid import UUID

    from syncr_api.core.patches import Patched
    from syncr_api.templates.records import TemplateRecord
    from syncr_domain.identifiers import AreaId, DayTypeId
    from syncr_domain.templates import BindingTarget


@dataclass(frozen=True, slots=True)
class DayTypeDeclaration:
    """One kind of day to declare. A name, and nothing else to say about it."""

    name: str


@dataclass(frozen=True, slots=True)
class TemplateDeclaration:
    """One day shape to declare, for a day type that has none yet."""

    day_type_id: DayTypeId
    name: str


@dataclass(frozen=True, slots=True)
class TemplateChange:
    """What one ``PATCH`` asked to change on a shape.

    The day type is absent. A shape IS the shape of its day type and there is exactly one per
    day type, so moving one is indistinguishable from declaring a shape for the other day type.
    """

    name: Patched[str]

    def applied_to(self, current: TemplateRecord) -> TemplateRecord:
        """``current`` with every field this change stated replaced."""
        return replace(current, name=resolved(self.name, current.name))


@dataclass(frozen=True, slots=True)
class EntryContent:
    """What an entry holds, resolved from whichever kind was declared.

    The persistence shape of the pairing rule. Only the two declarations below produce one, so
    a repository can take four columns' worth of values without deciding anything about which
    combination is legal.
    """

    kind: TemplateEntryKind
    area_id: AreaId | None
    binding_target: BindingTarget | None
    binding_ref: UUID | None


@dataclass(frozen=True, slots=True)
class ConcreteEntry:
    """A specific routine or habit at a target time.

    The Area is optional and is a statement about reporting rather than about content: the bound
    routine or habit already names what happens.
    """

    span: EntrySpan
    binding_target: BindingTarget
    binding_ref: UUID
    area_id: AreaId | None

    def content(self) -> EntryContent:
        """This entry's four stored content values."""
        return EntryContent(
            kind=TemplateEntryKind.CONCRETE,
            area_id=self.area_id,
            binding_target=self.binding_target,
            binding_ref=self.binding_ref,
        )


@dataclass(frozen=True, slots=True)
class SlotEntry:
    """An Area and a duration, with the content bound at solve time.

    "One hour of Learning" is the whole declaration. Which task or habit occurrence fills it is
    the solver's answer, taken when it has the most information.
    """

    span: EntrySpan
    area_id: AreaId

    def content(self) -> EntryContent:
        """This entry's four stored content values. A slot holds no binding at all."""
        return EntryContent(
            kind=TemplateEntryKind.SLOT,
            area_id=self.area_id,
            binding_target=None,
            binding_ref=None,
        )


type EntryDeclaration = ConcreteEntry | SlotEntry


@dataclass(frozen=True, slots=True)
class EntryChange:
    """What one ``PATCH`` asked to change on an entry: its span, and nothing else."""

    target_time: Patched[time]
    duration_minutes: Patched[int]
    flex_band_minutes: Patched[int]

    def applied_to(self, current: EntrySpan) -> EntrySpan:
        """``current`` with every field this change stated replaced.

        Built through the span's own constructor, so a patch that would leave the entry off the
        grid is refused by the rule the declaration was subject to rather than by a second
        statement of it here.
        """
        return EntrySpan(
            target_time=resolved(self.target_time, current.target_time),
            duration_minutes=resolved(self.duration_minutes, current.duration_minutes),
            flex_band_minutes=resolved(self.flex_band_minutes, current.flex_band_minutes),
        )
