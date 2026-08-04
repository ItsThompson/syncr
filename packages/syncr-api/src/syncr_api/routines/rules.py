"""How the boundary states a span the domain refused.

One mapping, in one place. Every invariant on a routine's span belongs to
``syncr_domain.routines``, so this module adds no rule: it turns the domain's refusal into the
status the boundary owes it, which is 422, and names the field the caller has to fix.

The field name is converted with the same generator the wire schemas use for their aliases, so
a refusal names ``minDurationMinutes`` exactly as the request that carried it did. Spelling it
out here would be a second statement of the casing rule, and the two would drift the first time
a field was renamed.

A create and a patch share this. That is why the rule is stated over a MERGED span rather than
over a request: lowering a target below a stored floor and raising a floor above a stored target
are the same violation, and a schema can see neither.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from pydantic.alias_generators import to_camel

from syncr_api.core.errors import FieldError, ValidationFailed
from syncr_domain.routines import RoutineError

if TYPE_CHECKING:
    from collections.abc import Iterator


@contextmanager
def stated_rejection() -> Iterator[None]:
    """Turn a refused routine span into a 422 that names the field and the remedy."""
    try:
        yield
    except RoutineError as error:
        raise ValidationFailed(
            f"The routine was not accepted: {error}. Nothing was changed, and every routine "
            "that already exists still reads as it did. A target and a floor are legal only "
            "with respect to each other, so send both in one request when both have to move.",
            errors=[FieldError(field=to_camel(error.field.value), message=str(error))],
        ) from error
