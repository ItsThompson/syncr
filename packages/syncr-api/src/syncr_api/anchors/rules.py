"""What an anchor-type declaration has to satisfy before it is stored.

Three of these are geometry rules checked without computing any geometry, and all three are
rejected **at the boundary** rather than at solve time. That placement is the requirement, not
an optimization: a type whose prep collides with its transit produces a shadow that cannot be
laid out, and discovering that during a solve would surface as a plan that will not compute
rather than as a field to change. Rejected here, the notice sits inline on the anchor type in
amber, states which member to change, and appears while the user is editing the thing that is
wrong.

Each of the three is also a check constraint on the table. These functions are what state the
reason; the constraints are the guarantee.

**The guard on ``prep_duration_minutes > 0`` is load-bearing.** With no prep there is nothing
for transit to collide with. Without the guard the rule rejects a type with transit and no prep,
which is the rendered ``Lecture`` (`Pre 0m`, `Transit 30m`), and the shadow-geometry fixture
cannot be built. :func:`require_prep_clear_of_transit` therefore returns early, and a test
asserts the transit-only case is accepted rather than only that the collision case is refused.

The two reference rules are stated over records the tenant already holds, so they live here
rather than in a request schema: a schema sees one request and cannot see the tenant's Areas.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.anchors.config import (
    ANCHOR_TYPE_RESOURCE,
    ANCHOR_TYPES_MAX,
    FORBIDS_AREAS,
    FORBIDS_EVERYTHING,
    FORBIDS_NOTHING,
    POST_SCOPE_LABEL,
    POST_SCOPE_LABELS,
    POST_SCOPES,
)
from syncr_api.areas.config import AREA_RESOURCE
from syncr_api.calendars.config import SOURCE_RESOURCE
from syncr_api.core.errors import Conflict, FieldError, ValidationFailed

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from syncr_api.anchors.records import AnchorTypeId, AnchorTypeRecord, AnchorTypeSpecification
    from syncr_api.calendars.records import CalendarSourceId
    from syncr_domain.identifiers import AreaId

# The three-way choice, in the words the form uses, so a rejection names the control the user is
# looking at rather than the column.
_SCOPE_CHOICES = ", ".join(POST_SCOPE_LABELS[scope] for scope in POST_SCOPES)
_SCOPE_CONTROL = f'"{POST_SCOPE_LABEL}: {_SCOPE_CHOICES}"'


def require_a_transit_lead_past_its_duration(specification: AnchorTypeSpecification) -> None:
    """Refuse an outbound leg that would still be travelling when the anchor started.

    A lead shorter than the journey means leaving too late to arrive on time, which is not a
    journey to the commitment. An absent lead is the abutting default and always satisfies this.
    """
    lead = specification.transit_lead_minutes
    if lead is None or lead >= specification.transit_duration_minutes:
        return
    raise ValidationFailed(
        f"A transit lead of {lead} minutes is shorter than the "
        f"{specification.transit_duration_minutes}-minute journey, so the outbound leg would "
        "still be travelling when the commitment started. Nothing was changed and every other "
        "anchor type still reads as it did. Raise the lead to at least the journey, or leave it "
        "empty to leave exactly late enough to arrive on time.",
        errors=[
            FieldError(
                field="transitLeadMinutes",
                message=(
                    "must be at least transitDurationMinutes "
                    f"({specification.transit_duration_minutes}), or empty to abut the anchor"
                ),
            )
        ],
    )


def require_prep_clear_of_transit(specification: AnchorTypeSpecification) -> None:
    """Refuse a prep block that would still be running when the outbound leg left.

    Returns early when the type declares no prep. That guard is load-bearing: with no prep there
    is nothing to collide, and without it a type with transit and no prep is rejected, which is
    the rendered ``Lecture``.
    """
    if specification.prep_duration_minutes == 0:
        return
    transit_lead = specification.effective_transit_lead_minutes
    needed = specification.prep_duration_minutes + transit_lead
    if specification.prep_lead_minutes >= needed:
        return
    raise ValidationFailed(
        f"A prep lead of {specification.prep_lead_minutes} minutes leaves prep running when "
        f"the outbound leg leaves: {specification.prep_duration_minutes} minutes of prep plus "
        f"a {transit_lead}-minute transit lead needs a prep lead of at least {needed}. Nothing "
        "was changed and every other anchor type still reads as it did. Change one of the "
        f"three: raise the prep lead to {needed}, shorten the prep, or shorten the transit "
        "lead.",
        errors=[
            FieldError(
                field="prepLeadMinutes",
                message=(
                    f"must be at least {needed}, which is prepDurationMinutes "
                    f"({specification.prep_duration_minutes}) plus the transit lead "
                    f"({transit_lead})"
                ),
            )
        ],
    )


def require_a_scope_matching_its_areas(specification: AnchorTypeSpecification) -> None:
    """Refuse a recovery scope that disagrees with the Areas it names.

    The list is non-empty for exactly one of the three scopes. An empty list once meant "forbids
    everything", which reads as an oversight rather than as a decision, so the choice is stated
    on the scope and the list only carries the members of the one scope that has members.
    """
    named = len(specification.forbidden_area_ids)
    if specification.forbids_named_areas == (named > 0):
        return
    if specification.forbids_named_areas:
        detail = (
            f'A recovery window set to forbid "{POST_SCOPE_LABELS[FORBIDS_AREAS]}" names no '
            "Areas, so it would forbid nothing. Nothing was changed. Name at least one Area, "
            f'or set {_SCOPE_CONTROL} to "{POST_SCOPE_LABELS[FORBIDS_NOTHING]}" or '
            f'"{POST_SCOPE_LABELS[FORBIDS_EVERYTHING]}".'
        )
        message = "must name at least one Area when the scope forbids named Areas"
    else:
        detail = (
            f'A recovery window set to forbid "{POST_SCOPE_LABELS[specification.post_scope]}" '
            f"also names {named} Area(s), which it would ignore. Nothing was changed. Clear the "
            f'Areas, or set {_SCOPE_CONTROL} to "{POST_SCOPE_LABELS[FORBIDS_AREAS]}" so they '
            "take effect."
        )
        message = "must be empty unless the scope forbids named Areas"
    raise ValidationFailed(detail, errors=[FieldError(field="forbiddenAreaIds", message=message)])


def require_declared_areas(
    specification: AnchorTypeSpecification, declared: Collection[AreaId]
) -> None:
    """Refuse an Area this tenant has not declared, wherever the specification named it.

    Answered the same way whether the identifier is unknown or belongs to another tenant, so the
    response discloses nothing about which.
    """
    unknown = [area_id for area_id in specification.referenced_area_ids if area_id not in declared]
    if not unknown:
        return
    fields = _named_area_fields(specification, unknown)
    raise ValidationFailed(
        f"No {AREA_RESOURCE} matches {len(unknown)} of the identifiers this anchor type names, "
        "so its prep, transit, or recovery could not be attributed. Nothing was changed and "
        "every other anchor type still reads as it did. Declare the Area first: prep and "
        "transit consume the budget of the Area they belong to.",
        errors=fields,
    )


def require_a_known_source(
    specification: AnchorTypeSpecification, declared: Collection[CalendarSourceId]
) -> None:
    """Refuse a match rule naming a calendar source this tenant does not have.

    The column carries no foreign key, because both foreign-key behaviors are wrong for it, so
    this is where a rule naming nothing is caught. A source removed AFTER the rule was written
    simply stops matching, because every anchor of a removed source goes with it.
    """
    source_id = specification.match_source_id
    if source_id is None or source_id in declared:
        return
    raise ValidationFailed(
        f"No {SOURCE_RESOURCE} matches that identifier, so a rule scoped to it would match "
        "nothing. Nothing was changed and every other anchor type still reads as it did. Add "
        "the calendar first, or leave the source empty to match commitments from every source.",
        errors=[
            FieldError(
                field="matchSourceId", message=f"No {SOURCE_RESOURCE} matches that identifier."
            )
        ],
    )


def require_an_unused_name(
    name: str, existing: Sequence[AnchorTypeRecord], *, apart_from: AnchorTypeId | None = None
) -> None:
    """Refuse a name another type already holds.

    The matched type is shown ON the anchor, so two types sharing a name would leave a reader
    unable to tell which rule fired.
    """
    if any(row.name == name and row.id != apart_from for row in existing):
        raise Conflict(
            f"Another {ANCHOR_TYPE_RESOURCE} already carries that name. Nothing was changed. "
            "The matched type is shown on the anchor, so two types cannot share one name. "
            "Every other anchor type still reads as it did."
        )


def require_room_for_another_type(existing: Sequence[AnchorTypeRecord]) -> None:
    """Refuse the type past the bound on how many one tenant may declare.

    A hand-authored rules table evaluated in order for every anchor of every sync. The bound is
    far above what a person writes; what it stops is an unbounded list being evaluated per
    anchor.
    """
    if len(existing) < ANCHOR_TYPES_MAX:
        return
    raise Conflict(
        f"This tenant already holds {ANCHOR_TYPES_MAX} anchor types, which is the most syncr "
        "evaluates. Nothing was changed and every existing type still matches as it did. Remove "
        "one that no longer matches anything, or widen an existing rule instead of adding a type."
    )


def validate(
    specification: AnchorTypeSpecification,
    *,
    declared_areas: Collection[AreaId],
    declared_sources: Collection[CalendarSourceId],
) -> None:
    """Every rule one specification is subject to, in the order a reader would check them.

    One entry point rather than five calls per writer, so a create and an edit cannot come under
    different subsets of the rules.
    """
    require_a_transit_lead_past_its_duration(specification)
    require_prep_clear_of_transit(specification)
    require_a_scope_matching_its_areas(specification)
    require_declared_areas(specification, declared_areas)
    require_a_known_source(specification, declared_sources)


def require_a_total_order(
    named: Sequence[AnchorTypeId], existing: Sequence[AnchorTypeRecord]
) -> None:
    """Refuse an order that is not a permutation of the types this tenant holds.

    The whole order or nothing. A partial order would leave the unnamed types at positions the
    caller could not see, and first-match semantics make that a silent change to what every one
    of them matches.
    """
    held = [row.id for row in existing]
    complete = sorted(named, key=str) == sorted(held, key=str)
    if complete and len(set(named)) == len(named):
        return
    raise ValidationFailed(
        f"A rule order has to name every {ANCHOR_TYPE_RESOURCE} exactly once. This one named "
        f"{len(named)} of {len(held)}. Nothing was changed and every rule still evaluates in the "
        "order it did. Send the whole order: moving one rule changes what every rule after it "
        "matches.",
        errors=[
            FieldError(
                field="anchorTypeIds",
                message=f"must name each of the {len(held)} anchor types exactly once",
            )
        ],
    )


def _named_area_fields(
    specification: AnchorTypeSpecification, unknown: Sequence[AreaId]
) -> list[FieldError]:
    """One field-level error per member that named an Area that does not exist."""
    unresolved = set(unknown)
    message = f"No {AREA_RESOURCE} matches that identifier."
    fields = [
        FieldError(field=field, message=message)
        for field, area_id in (
            ("prepAreaId", specification.prep_area_id),
            ("transitAreaId", specification.transit_area_id),
        )
        if area_id in unresolved
    ]
    if any(area_id in unresolved for area_id in specification.forbidden_area_ids):
        fields.append(FieldError(field="forbiddenAreaIds", message=message))
    return fields
