"""What an Area declaration has to satisfy before it is stored.

Every rule here is stated over the Areas the tenant already holds, which is why they live at
the service layer rather than in a request schema: a schema sees one request and no rule here
is about one request. The unique index on ``(tenant_id, name)`` is the backstop for the name
rule; this is what states the reason for it in the response.

No rule here is about a budget. Percentages summing past 100 are a legitimate declaration and
are reported as ``oversubscription``, so there is deliberately nothing here that compares a
sum against 100.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.areas.config import AREA_RESOURCE, PROJECT_RESOURCE
from syncr_api.core.errors import Conflict, FieldError, ValidationFailed
from syncr_domain.pigments import PIGMENT_COUNT, is_ramp_exhausted

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_api.areas.records import AreaRecord
    from syncr_domain.identifiers import AreaId

FULL_RAMP_REFUSAL = (
    f"The ramp holds {PIGMENT_COUNT} pigments and each one is already held by an {AREA_RESOURCE}, "
    "so there is no step left to deal and this one was not stored. Nothing was changed. "
    f"Every {AREA_RESOURCE} that already exists still reads as it did, and can still be renamed "
    f"or have its floor and share changed. New work fits inside one as a {PROJECT_RESOURCE}, "
    f"which inherits its {AREA_RESOURCE}'s allocation rather than carrying one of its own."
)


def find_area(area_id: AreaId, areas: Sequence[AreaRecord]) -> AreaRecord | None:
    """The Area with this identifier among ones already read, or ``None``."""
    return next((area for area in areas if area.id == area_id), None)


def require_room_on_the_ramp(existing: Sequence[AreaRecord]) -> None:
    """Refuse a declaration the ramp has no step left to deal.

    Stated over the rows because the deal is: a step is derived from how many Areas already
    hold one, so the count is where an Area with no step of its own is refused rather than
    dealt one another Area holds. The predicate is the domain's, so the bound and the deal
    cannot disagree about where the ramp runs out.
    """
    if is_ramp_exhausted(len(existing)):
        raise ValidationFailed(FULL_RAMP_REFUSAL)


def require_an_unused_name(
    name: str, existing: Sequence[AreaRecord], *, apart_from: AreaId | None = None
) -> None:
    """Refuse a name another Area already holds.

    Not a nicety. Past twelve Areas the pigment ramp repeats and identity rests on the hatch
    and the name, so two Areas sharing a name would leave a wedge with nothing to identify it.
    """
    if any(area.name == name and area.id != apart_from for area in existing):
        raise Conflict(
            "Another Area already carries that name. Nothing was changed. Past twelve Areas "
            "the pigment ramp repeats and identity rests on the hatch and the name, so two "
            "Areas cannot share one. Every other Area still reads as it did."
        )


def require_an_unheld_pigment(
    pigment_index: int, existing: Sequence[AreaRecord], *, apart_from: AreaId | None = None
) -> None:
    """Refuse a step of the ramp another Area already holds.

    Stated over the rows for the same reason the name rule is: which steps are held is a fact
    about the tenant's Areas rather than about one request. The cap on the count is what keeps
    a declaration off a shared step; this is what keeps a re-pick off one, so the collision is
    not reachable in two ``PATCH`` requests either.
    """
    holder = next(
        (
            area
            for area in existing
            if area.pigment_index == pigment_index and area.id != apart_from
        ),
        None,
    )
    if holder is not None:
        raise Conflict(
            f"Another Area already holds that step of the ramp: {holder.name}. Nothing was "
            "changed. This Area still holds the step it had, and every step no other Area "
            "holds is still available to it."
        )


def require_a_declared_parent(parent_id: AreaId, existing: Sequence[AreaRecord]) -> None:
    """Refuse a parent this tenant has not declared.

    Answered the same way whether the identifier is unknown or belongs to another tenant, so
    the response discloses nothing about which.
    """
    if find_area(parent_id, existing) is None:
        raise ValidationFailed(
            f"No {AREA_RESOURCE} matches that identifier, so this Area cannot nest under it. "
            "Nothing was changed. Every Area that already exists still reads as it did.",
            errors=unknown_area("parentId"),
        )


def unknown_area(field: str) -> list[FieldError]:
    """The field-level error a request naming an Area that does not exist carries."""
    return [FieldError(field=field, message=f"No {AREA_RESOURCE} matches that identifier.")]
