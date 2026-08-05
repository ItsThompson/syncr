"""What an apply request asked for, as a value the service takes.

A route reads a body and a service applies a rule, so the shape between them is neither the wire's
nor the domain's. This is the one place a list of wire rows becomes a mapping keyed by the Area it
addresses, which is also where a request naming one Area twice is refused: two shares for one Area
are two instructions, and applying either silently would be a budget the user did not author.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.reviews.rules import require_one_share_per_area

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from decimal import Decimal

    from syncr_domain.identifiers import AreaId


@dataclass(frozen=True, slots=True)
class AppliedShares:
    """The shares one apply asked to declare, one per Area."""

    by_area: Mapping[AreaId, Decimal]


def shares_asked_for(rows: Sequence[tuple[AreaId, Decimal]]) -> AppliedShares:
    """The request's rows as one share per Area, or a 422 if it names one Area twice."""
    require_one_share_per_area(area_id for area_id, _ in rows)
    return AppliedShares(by_area=dict(rows))
