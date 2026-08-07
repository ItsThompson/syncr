"""Waiting on an operation: poll, back off, and end with the code the outcome deserves.

SSE is out of CLI scope, so the ``Operation`` resource is polled. Three rules shape the loop.

**Polling is capped and backs off.** A tight poll on a long solve should not hammer the API, so
the interval doubles from the configured one up to a ceiling. The first poll is at the configured
interval, which is what makes a fast solve answer fast.

**A timeout is not a failure.** It names the operation so the wait is resumable rather than lost,
and it exits 10.

**The clock and the sleep are injected.** A test drives a supersession and a timeout without
waiting for either, and the loop is the same loop in both.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from syncr_cli.errors import WaitTimedOut
from syncr_cli.wire.operation import Operation

if TYPE_CHECKING:
    from collections.abc import Callable

    from syncr_cli.api_client import ApiClient

# How the interval grows, and how far. Doubling reaches the ceiling in four polls from the default
# 500ms, so a solve that takes a minute is polled a dozen times rather than 120.
BACKOFF_FACTOR: Final = 2
MAX_POLL_INTERVAL_MS: Final = 5_000

_MS_PER_SECOND: Final = 1000


def wait_for_operation(
    *,
    client: ApiClient,
    operation_id: str,
    poll_interval_ms: int,
    timeout_s: int,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
) -> Operation:
    """Poll ``operation_id`` until it is terminal, or say it timed out and name it."""
    deadline = monotonic() + timeout_s
    interval_ms = poll_interval_ms
    while True:
        operation = Operation.read(client.read_operation(operation_id), "operation")
        if operation.is_terminal:
            return operation
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise WaitTimedOut(
                f"the {operation.kind} {operation_id} was still {operation.status.value} after "
                f"{timeout_s}s, so this wait ended. The work is not cancelled: read it again "
                f"with the same id to resume the wait.",
                operation=operation,
            )
        sleep(min(interval_ms / _MS_PER_SECOND, remaining))
        interval_ms = min(interval_ms * BACKOFF_FACTOR, MAX_POLL_INTERVAL_MS)
