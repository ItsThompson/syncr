"""The clock seam.

A service that reads the wall clock itself cannot be asked what it would do an hour
from now, so every service that needs the current instant takes one of these as a
constructor dependency. Session expiry, the sliding window, and the absolute cap are
all clock arithmetic, and a test that had to sleep for them would either be slow or
be a test of ``time.sleep``.

Instants are always timezone-aware and always UTC at this boundary. Local wall time
is a presentation concern of the zone layer, never a stored value.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

type Clock = Callable[[], datetime]


def utc_now() -> datetime:
    """The current instant, timezone-aware and in UTC."""
    return datetime.now(UTC)
