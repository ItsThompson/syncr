"""The header, the retention window, the two states, and the column bounds.

Keys are scoped per tenant AND per route, so two clients cannot collide and one client
reusing a key on a different route is a different key rather than a conflict.

They are retained 24 hours: long enough for any realistic retry, short enough that the
table stays small. A row past its window is treated as unseen by the next request carrying
the same key, so correctness does not depend on the sweep having run.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final, Literal

IDEMPOTENCY_KEYS_TABLE = "idempotency_keys"

IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"

RETENTION = timedelta(hours=24)

type KeyState = Literal["in_flight", "completed"]
IN_FLIGHT: Final[KeyState] = "in_flight"
COMPLETED: Final[KeyState] = "completed"
KEY_STATES: Final = (IN_FLIGHT, COMPLETED)

STATE_MAX_LENGTH = 16
# A key is client-chosen. Long enough for a UUID, a ULID, or a request id from any client,
# and bounded so a caller cannot make the primary key arbitrarily wide.
KEY_MAX_LENGTH = 200
ROUTE_MAX_LENGTH = 200
# sha256, hex.
REQUEST_HASH_LENGTH = 64

# What a caller in flight is asked to wait before retrying. The work it is waiting on is one
# request, so the answer is "about now, but not this instant".
IN_FLIGHT_RETRY_AFTER_SECONDS = 1

REPLAYED_DETAIL = (
    "This request was already applied under the same idempotency key, so the original "
    "response is returned and nothing was applied twice."
)
IN_FLIGHT_DETAIL = (
    "A request with this idempotency key is still being applied. Retry shortly to receive "
    "its response. Nothing was applied twice."
)
REUSED_KEY_DETAIL = (
    "This idempotency key was already used for a different request, so it was refused. "
    "Nothing was changed. Use a new key for a new request, or resend the original one."
)
