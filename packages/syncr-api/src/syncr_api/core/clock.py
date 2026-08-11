"""The clock seam.

A service that reads the wall clock itself cannot be asked what it would do an hour
from now, so every service that needs the current instant takes one of these as a
constructor dependency. Session expiry, the sliding window, and the absolute cap are
all clock arithmetic, and a test that had to sleep for them would either be slow or
be a test of ``time.sleep``.

Instants are always timezone-aware and always UTC at this boundary. Local wall time
is a presentation concern of the zone layer, never a stored value.

``utc_now`` is also the only place this package reads the wall clock, so the offset below
moves every reader that takes the clock as a dependency, in the api process and in the
worker process alike, and none of them is rewired to get it.

THREE CLOCKS THE OFFSET DOES NOT MOVE, so a reader that shifts it and then compares one of
these is comparing two clocks:

- **Postgres's own clock.** ``now()`` in the server, and every column defaulted from it,
  is the database's wall clock, which nothing in this process reaches. That is the point
  rather than a limitation: a container-wide fake would lie to Postgres too, and every
  stored instant would become part of the fiction.
- **The timestamp on a log line**, which structlog's own ``TimeStamper`` takes.
- **The browser's ``Date.now()``**, which the week grid reads to place the current hour.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError

if TYPE_CHECKING:
    from collections.abc import Callable

type Clock = Callable[[], datetime]

# How far this process's clock runs ahead of the wall clock. Prefixed and absent from
# `EnvSettings`, unlike every deployment-wide setting, because it is a development-only
# seam rather than configuration: settings construction is refused with it set anywhere but
# development, and this module is the only reader of it in the repository.
CLOCK_OFFSET_ENV_VAR = "SYNCR_CLOCK_OFFSET"

_NO_OFFSET = timedelta(0)

# The duration is read with pydantic rather than by a parser written here: it is already
# this package's configuration reader, it accepts the ISO 8601 spelling and the
# ``HH:MM:SS`` one, and it REFUSES A BARE NUMBER, so a value whose unit the writer left
# implicit fails instead of meaning whichever unit a reader picked.
_DURATION = TypeAdapter(timedelta)

_SPELLINGS = "an ISO 8601 duration such as `P3D`, `-PT2H` or `PT90M`, or `HH:MM:SS`"


def clock_offset() -> timedelta:
    """How far :func:`utc_now` runs ahead of the wall clock. Zero unless the environment says.

    An EMPTY value means no offset, which is the case worth spelling out: Compose
    interpolation of an unset variable produces an empty value that overrides the file the
    value would otherwise have come from.

    A value no reader can read raises, rather than resolving to zero. A silent zero would
    make a misspelled duration indistinguishable from a clock nobody moved.
    """
    named = os.environ.get(CLOCK_OFFSET_ENV_VAR, "").strip()
    if not named:
        return _NO_OFFSET
    try:
        return _DURATION.validate_python(named)
    except ValidationError as unreadable:
        message = (
            f"{CLOCK_OFFSET_ENV_VAR}={named!r} is not a duration. Write {_SPELLINGS}, or unset it."
        )
        raise ValueError(message) from unreadable


def utc_now() -> datetime:
    """The current instant, timezone-aware and in UTC, shifted by :func:`clock_offset`."""
    return datetime.now(UTC) + clock_offset()
