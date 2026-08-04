"""What a request asked to declare or change, as the service takes it.

These sit between the route that read the request and the service that applies it, so the
service never imports a wire schema and the route never decides anything.

``AnchorTypeChange`` is thirteen three-valued fields and it is verbose on purpose. Absent leaves
the stored value alone, a value replaces it, and null clears one of the five nullable members.
The distinction is what makes both intentions reachable: ``transitLeadMinutes: null`` restores
the abutting default, and omitting the field keeps whatever lead is stored. Collapsing the two
would make one of them unreachable, and the one that would go is the one that says "leave
exactly late enough to arrive on time".

A change is applied onto the stored specification and the merged result is what the boundary
rules see. That is why the rules take a specification rather than a change: an edit that lowers
the prep lead and an edit that raises the transit duration are the same collision, and a rule
stated over a change would have to reconstruct the stored value to notice.

``RuleOrder`` and ``TypeAssignment`` carry no three-valued field at all, because neither is a
partial update. A reorder states the whole order, and an assignment states the whole answer:
``anchor_type_id`` of ``None`` there means "this is not any of my types", which is a decision the
user is entitled to make and which a later rule match must not undo.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from syncr_api.core.patches import Absent, resolved

if TYPE_CHECKING:
    from syncr_api.anchors.config import PostScope
    from syncr_api.anchors.records import AnchorTypeId, AnchorTypeSpecification
    from syncr_api.calendars.records import CalendarSourceId
    from syncr_api.core.patches import Patched
    from syncr_domain.identifiers import AreaId


@dataclass(frozen=True, slots=True)
class AnchorTypeChange:
    """What one ``PATCH`` asked to change on an anchor type.

    ``rule_order`` is absent from this shape. Position is changed through the reorder route,
    because moving one rule changes what every rule after it matches, so a caller that named one
    position would be stating a fraction of the change it was making.
    """

    name: Patched[str]
    match_title_contains: Patched[str | None]
    match_source_id: Patched[CalendarSourceId | None]
    prep_lead_minutes: Patched[int]
    prep_duration_minutes: Patched[int]
    prep_area_id: Patched[AreaId | None]
    transit_lead_minutes: Patched[int | None]
    transit_duration_minutes: Patched[int]
    return_transit_minutes: Patched[int]
    transit_area_id: Patched[AreaId | None]
    post_buffer_minutes: Patched[int]
    post_scope: Patched[PostScope]
    forbidden_area_ids: Patched[tuple[AreaId, ...]]

    def changes_a_match_rule(self) -> bool:
        """Whether this change touches what the rule matches.

        A geometry edit regenerates shadows for the anchors already typed; a MATCH edit changes
        which anchors are typed at all, so it needs a re-evaluation pass as well.
        """
        return not isinstance(self.match_title_contains, Absent) or not isinstance(
            self.match_source_id, Absent
        )

    def applied_to(self, current: AnchorTypeSpecification) -> AnchorTypeSpecification:
        """``current`` with every field this change stated replaced."""
        return replace(
            current,
            name=resolved(self.name, current.name),
            match_title_contains=resolved(self.match_title_contains, current.match_title_contains),
            match_source_id=resolved(self.match_source_id, current.match_source_id),
            prep_lead_minutes=resolved(self.prep_lead_minutes, current.prep_lead_minutes),
            prep_duration_minutes=resolved(
                self.prep_duration_minutes, current.prep_duration_minutes
            ),
            prep_area_id=resolved(self.prep_area_id, current.prep_area_id),
            transit_lead_minutes=resolved(self.transit_lead_minutes, current.transit_lead_minutes),
            transit_duration_minutes=resolved(
                self.transit_duration_minutes, current.transit_duration_minutes
            ),
            return_transit_minutes=resolved(
                self.return_transit_minutes, current.return_transit_minutes
            ),
            transit_area_id=resolved(self.transit_area_id, current.transit_area_id),
            post_buffer_minutes=resolved(self.post_buffer_minutes, current.post_buffer_minutes),
            post_scope=resolved(self.post_scope, current.post_scope),
            forbidden_area_ids=resolved(self.forbidden_area_ids, current.forbidden_area_ids),
        )


@dataclass(frozen=True, slots=True)
class RuleOrder:
    """The whole evaluation order, as one request stated it.

    Every type the tenant holds, exactly once. A partial order would leave the unnamed types at
    positions the caller could not see, and first-match semantics make that a silent change to
    what every one of them matches.
    """

    anchor_type_ids: tuple[AnchorTypeId, ...]


@dataclass(frozen=True, slots=True)
class TypeAssignment:
    """The type one occurrence was retyped to. ``None`` means "not any of my types"."""

    anchor_type_id: AnchorTypeId | None
