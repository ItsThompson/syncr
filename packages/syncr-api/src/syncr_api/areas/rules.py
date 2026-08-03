"""What an Area declaration has to satisfy before it is stored.

Both rules are stated over the Areas the tenant already holds, which is why they live at the
service layer rather than in a request schema: a schema sees one request and neither rule is
about one request. The unique index on ``(tenant_id, name)`` is the backstop for the first;
this is what states the reason for it in the response.

Neither rule is about a budget. Percentages summing past 100 are a legitimate declaration and
are reported as ``oversubscription``, so there is deliberately nothing here that compares a
sum against 100.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.areas.config import AREA_RESOURCE
from syncr_api.core.errors import Conflict, FieldError, ValidationFailed

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_api.areas.records import AreaRecord
    from syncr_domain.identifiers import AreaId


def find_area(area_id: AreaId, areas: Sequence[AreaRecord]) -> AreaRecord | None:
    """The Area with this identifier among ones already read, or ``None``."""
    return next((area for area in areas if area.id == area_id), None)


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
