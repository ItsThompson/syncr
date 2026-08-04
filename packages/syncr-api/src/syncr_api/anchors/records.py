"""The immutable views of an anchor row and an anchor-type row.

A repository hands back one of these rather than a mapped instance, so a service cannot
trigger a load it did not ask for and nothing downstream can change a row by assignment.

``AnchorTypeSpecification`` is the whole shadow declaration: the four durations, the two leads,
the two Areas, and the recovery scope. It is a value of its own rather than fourteen fields on
the record for two reasons. A ``PATCH`` merges onto it, so a partial update has one shape to
merge into rather than a field-by-field resolution repeated per column. And the boundary rules
in :mod:`syncr_api.anchors.rules` are stated over it, so a create and an edit are checked by
the same code against the same value rather than by two statements of one rule.

``ShadowDeclaration`` is which of the four products a type declares, computed from the zeroes
alone and with no instant anywhere in it. It exists because an untyped anchor is opaque busy
time with no shadow of any kind, and that has to be something a reader can ask rather than
something a reader infers from a null type identifier.

**No geometry is here.** Nothing in this module computes a span. What a prep block's interval
IS belongs to the shadow generator, which reads a specification and an anchor's interval; what
this module answers is what the type DECLARES.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar
from uuid import UUID

from syncr_api.anchors.config import (
    FORBIDS_AREAS,
    FORBIDS_NOTHING,
    RULE_MATCH,
    UNMATCHED,
    USER_OVERRIDE,
)

if TYPE_CHECKING:
    from syncr_api.anchors.config import AnchorTypeSource, PostScope
    from syncr_api.calendars.records import CalendarSourceId
    from syncr_domain.identifiers import AreaId, TenantId
    from syncr_domain.intervals import Interval

type AnchorId = UUID
type AnchorTypeId = UUID


@dataclass(frozen=True, slots=True)
class ShadowDeclaration:
    """Which products a type declares, before any geometry is computed.

    Whether a declared prep or transit product becomes a block or a forbidden window depends
    on whether it has an Area, which is the generator's read of the same specification. This
    answers the prior question: whether the product exists at all.
    """

    prep: bool
    outbound_transit: bool
    return_transit: bool
    recovery: bool

    EMPTY: ClassVar[ShadowDeclaration]

    @property
    def is_empty(self) -> bool:
        """Whether this declares nothing, which is what an untyped anchor casts."""
        return not (self.prep or self.outbound_transit or self.return_transit or self.recovery)

    @classmethod
    def of(cls, specification: AnchorTypeSpecification | None) -> ShadowDeclaration:
        """What an anchor carrying this specification casts, or nothing for an untyped one.

        A zero on any member collapses that product, and a recovery window needs both a
        non-zero buffer and a scope that forbids something.
        """
        if specification is None:
            return cls.EMPTY
        return cls(
            prep=specification.prep_duration_minutes > 0,
            outbound_transit=specification.transit_duration_minutes > 0,
            return_transit=specification.return_transit_minutes > 0,
            recovery=specification.post_buffer_minutes > 0
            and specification.post_scope != FORBIDS_NOTHING,
        )


ShadowDeclaration.EMPTY = ShadowDeclaration(
    prep=False, outbound_transit=False, return_transit=False, recovery=False
)


@dataclass(frozen=True, slots=True)
class AnchorTypeSpecification:
    """Everything one anchor type declares, apart from its identity and its rule order.

    ``transit_lead_minutes`` is nullable and null is not zero. Null means the outbound leg
    abuts the anchor, so it leaves exactly late enough to arrive on time; zero would mean a
    leg that starts at the anchor and is therefore not a journey to it at all. Every reader
    goes through :attr:`effective_transit_lead_minutes` so the default has one statement.
    """

    name: str
    match_title_contains: str | None
    match_source_id: CalendarSourceId | None
    prep_lead_minutes: int
    prep_duration_minutes: int
    prep_area_id: AreaId | None
    transit_lead_minutes: int | None
    transit_duration_minutes: int
    return_transit_minutes: int
    transit_area_id: AreaId | None
    post_buffer_minutes: int
    post_scope: PostScope
    forbidden_area_ids: tuple[AreaId, ...]

    @property
    def effective_transit_lead_minutes(self) -> int:
        """How long before the anchor the outbound leg starts, with the default applied."""
        if self.transit_lead_minutes is None:
            return self.transit_duration_minutes
        return self.transit_lead_minutes

    @property
    def referenced_area_ids(self) -> tuple[AreaId, ...]:
        """Every Area this specification names, so one read confirms they all exist."""
        named = [self.prep_area_id, self.transit_area_id, *self.forbidden_area_ids]
        return tuple(dict.fromkeys(area_id for area_id in named if area_id is not None))

    @property
    def forbids_named_areas(self) -> bool:
        return self.post_scope == FORBIDS_AREAS


@dataclass(frozen=True, slots=True)
class AnchorTypeRecord:
    """One anchor type, as persistence knows it."""

    id: AnchorTypeId
    tenant_id: TenantId
    rule_order: int
    specification: AnchorTypeSpecification

    @property
    def name(self) -> str:
        """The type's name, which is what is shown on a matched anchor."""
        return self.specification.name

    def declared_shadow(self) -> ShadowDeclaration:
        return ShadowDeclaration.of(self.specification)


@dataclass(frozen=True, slots=True)
class AnchorRecord:
    """One imported commitment, as persistence knows it. Read-only in syncr.

    ``external_uid`` is half of the reconciliation key; the source is the other half. Two
    sources publishing one UID are two anchors, because two calendars can each hold the same
    meeting and excluding one must not remove the other's.

    ``location`` is stored and deliberately has no reader. Transit is declared per anchor type
    rather than derived from a location, which reinterprets PRD 3.4's "generated from a
    location": routing needs a maps integration, a home address, and a travel-mode preference,
    none of which is in this epic. The column exists so the fact is not discarded at ingest and
    a later epic does not need a backfill.
    """

    id: AnchorId
    tenant_id: TenantId
    source_id: CalendarSourceId
    external_uid: str
    series_uid: str | None
    title: str
    interval: Interval
    location: str | None
    anchor_type_id: AnchorTypeId | None
    type_overridden: bool
    possibly_stale: bool

    @property
    def type_source(self) -> AnchorTypeSource:
        """Where this anchor's type came from, which decides whether a rule may replace it.

        An override reads as an override even when it cleared the type. "This standup is not
        an interview" is a decision, and a later rule match must not undo it.
        """
        if self.type_overridden:
            return USER_OVERRIDE
        return UNMATCHED if self.anchor_type_id is None else RULE_MATCH
