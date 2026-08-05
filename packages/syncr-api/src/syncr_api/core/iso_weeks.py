"""Reading an ISO week out of a request, in one place.

Three route groups address a week by identifier: the budget report by query parameter, and the week
and concession routes by path segment. The identifier's shape is the domain's, so a route declares
no pattern of its own that could drift from ``IsoWeek.parse``, and the 422 a malformed one produces
is worded once rather than per caller.

The field name is passed in because it is the caller's own wire spelling, and a field error naming
``period`` on a route whose parameter is ``iso_week`` sends the client looking for a field it never
sent. Every path parameter this api declares is snake_cased, which is what these callers pass.
"""

from __future__ import annotations

from syncr_api.core.errors import FieldError, ValidationFailed
from syncr_domain.weeks import IsoWeek, IsoWeekError


def require_an_iso_week(named: str, *, field: str) -> IsoWeek:
    """``named`` as an ISO week, or a 422 naming the field and the shape it takes.

    The message states that nothing changed, because this parse happens before any write and a
    caller retrying a rejected request must know it is not retrying a partial one.
    """
    try:
        return IsoWeek.parse(named)
    except IsoWeekError as error:
        raise ValidationFailed(
            f"The {field} was not accepted: {error}. Nothing was changed.",
            errors=[FieldError(field=field, message=str(error))],
        ) from error
