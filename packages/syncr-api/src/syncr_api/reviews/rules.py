"""How an apply is refused, and the two shapes a request can get wrong.

Both refusals are about the SET the request names rather than about any one value, which is why
neither can be a schema rule: a share's range is bounded on the field, and these two need the whole
list, or the list against the tenant's own rows.

**An Area named twice is refused rather than resolved.** Two shares for one Area are two
instructions, and applying either silently would declare a budget the user did not author.

**An Area the tenant does not hold is refused, and nothing is applied.** A 422 rather than a 404:
the identifier is in the BODY, and the resource the request addresses is the review, which exists.
A partial application would leave a budget half revised with no way to tell which half, so the whole
request is refused before anything is written.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Final

from syncr_api.core.errors import FieldError, ValidationFailed
from syncr_api.reviews.config import AREA_FIELD, PERCENTAGES_FIELD

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable

    from syncr_domain.identifiers import AreaId

# How many identifiers a refusal names before it stops. A budget is bounded by how many life
# categories a person holds, so a refusal naming every unknown one is short; the bound is here so a
# hand-built request of a thousand rows cannot put a thousand identifiers in one message.
_NAMED_AT_MOST: Final = 5


def require_one_share_per_area(area_ids: Iterable[AreaId]) -> None:
    """Refuse a request naming one Area twice, before anything is written."""
    counted = Counter(area_ids)
    repeated = sorted(found for found, times in counted.items() if times > 1)
    if not repeated:
        return
    raise ValidationFailed(
        f"The {PERCENTAGES_FIELD} name {_listed(repeated)} more than once, and two shares for one "
        "Area are two instructions. Nothing was changed. Send one share per Area.",
        errors=[FieldError(field=PERCENTAGES_FIELD, message="one share per Area")],
    )


def require_declared_areas(area_ids: Iterable[AreaId], declared: Collection[AreaId]) -> None:
    """Refuse a request naming an Area this tenant has not declared, applying none of it."""
    unknown = sorted({found for found in area_ids if found not in declared})
    if not unknown:
        return
    raise ValidationFailed(
        f"No Area matches {_listed(unknown)}, so no share was applied. Nothing was changed: a "
        "budget half revised could not be told from one revised whole.",
        errors=[FieldError(field=AREA_FIELD, message="names an Area this tenant has not declared")],
    )


def _listed(area_ids: list[AreaId]) -> str:
    """The identifiers a refusal names, bounded so one request cannot set the message's size."""
    named = ", ".join(str(one) for one in area_ids[:_NAMED_AT_MOST])
    remaining = len(area_ids) - _NAMED_AT_MOST
    return named if remaining <= 0 else f"{named} and {remaining} more"
