"""Whether the weekly session was open when a mutation arrived, read from the request that says so.

``VE3``: only the caller knows whether the weekly session is open, because it is a mode of the
client's own screen rather than a state this application holds. A verdict transition recorded during
a session is what the early-catch product metric's numerator counts, so the answer has to cross the
wire.

**A header rather than a field on each body.** It is a property of the client's state at the moment
of the request rather than of the resource being changed, so a field would be repeated on every
mutation body that ever computes a verdict and omitted from the next one. Read from the raw request,
the way the idempotency key is, so it names no parameter of the resource in the OpenAPI document.

**Resolved through :data:`SessionModeDep`, and only where a verdict is computed.** The refusal below
is a 422 saying nothing was changed, which is true of a mutation and meaningless on a read: a
dependency that served a whole router would refuse a ``GET`` for a header that read has no use for.
So the alias is declared on the wiring of the paths that record a transition, and every other path
never reads it.

**A value this deployment cannot read is refused rather than treated as absent.** A client sending
``X-Syncr-Session-Mode: yes please`` would otherwise have every transition it caused recorded as a
miss, and the metric would report a number worse than the truth with nothing anywhere saying why. An
absent header is false, which is what every non-browser caller is: the maintainer, a CLI mutation,
and any client that has no session concept at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Final

from fastapi import Depends
from starlette.requests import Request  # noqa: TC002

from syncr_api.core.errors import FieldError, ValidationFailed

if TYPE_CHECKING:
    from collections.abc import Mapping

SESSION_MODE_HEADER: Final = "X-Syncr-Session-Mode"

# The words the header may carry, and what each says. Stated as data so the refusal below can name
# every accepted spelling without a second list going stale.
_READINGS: Final[Mapping[str, bool]] = {
    "true": True,
    "1": True,
    "false": False,
    "0": False,
}


def read_session_mode(request: Request) -> bool:
    """Whether this request states that the weekly session is open. Absent means it is not."""
    stated = request.headers.get(SESSION_MODE_HEADER)
    if stated is None:
        return False
    reading = _READINGS.get(stated.strip().lower())
    if reading is None:
        accepted = ", ".join(sorted(_READINGS))
        raise ValidationFailed(
            f"The {SESSION_MODE_HEADER} header carries a value this deployment cannot read, so "
            "nothing was changed. Send one of the accepted values, or send no header at all, which "
            "states that no weekly session is open.",
            errors=[
                FieldError(
                    field=SESSION_MODE_HEADER,
                    message=f"expected one of {accepted}, and this request states {stated!r}",
                )
            ],
        )
    return reading


type SessionModeDep = Annotated[bool, Depends(read_session_mode)]
"""The one way a route acquires this answer, declared by the wiring of a path that records."""
