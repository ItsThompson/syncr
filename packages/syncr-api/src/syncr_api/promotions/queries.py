"""Reading a promotion candidate's identifier out of a request path, in one place.

Both promotion routes are addressed by one, and the refusal is the domain's own: the shape is
``PromotionRef``'s, so no route declares a pattern of its own that could drift from it.

**The LENGTH is not checked here.** ``Path(max_length=...)`` on the route is the mechanism FastAPI
already has for it, and it answers before this function is reached, so a bound stated a second time
here would be a branch nothing can enter.
"""

from __future__ import annotations

from syncr_api.core.errors import FieldError, ValidationFailed
from syncr_domain.promotion import PromotionRef, PromotionRefError


def require_a_promotion_ref(named: str, *, field: str) -> PromotionRef:
    """``named`` as a promotion reference, or a 422 naming the field and the shape it takes.

    The message states that nothing changed, because this parse happens before any write and a
    caller retrying a rejected request must know it is not retrying a partial one.
    """
    try:
        return PromotionRef.parse(named)
    except PromotionRefError as error:
        raise ValidationFailed(
            f"The {field} was not accepted: {error}. Nothing was changed.",
            errors=[FieldError(field=field, message=str(error))],
        ) from error
