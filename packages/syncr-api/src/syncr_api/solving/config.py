"""The vocabularies the ``operations`` table is defined against.

The status set is a state machine, and which members are TERMINAL is what the two indexes
and the retention rule are stated over: at most one non-terminal solve exists per week, and
only terminal rows are ever pruned.

``superseded`` is terminal and is NOT an error. It is the expected outcome of editing
quickly: the user's own later change displaced a solve, and a follow-up is already running.
Presenting it as a failure would make normal use look broken.
"""

from __future__ import annotations

from typing import Final, Literal

OPERATIONS_TABLE = "operations"

type OperationKind = Literal["solve", "materialize", "calendar_sync", "projection"]
SOLVE: Final[OperationKind] = "solve"
CALENDAR_SYNC: Final[OperationKind] = "calendar_sync"
OPERATION_KINDS: Final = ("solve", "materialize", "calendar_sync", "projection")

type OperationStatus = Literal["pending", "running", "succeeded", "failed", "superseded"]
PENDING: Final[OperationStatus] = "pending"
RUNNING: Final[OperationStatus] = "running"
SUCCEEDED: Final[OperationStatus] = "succeeded"
FAILED: Final[OperationStatus] = "failed"
SUPERSEDED: Final[OperationStatus] = "superseded"
OPERATION_STATUSES: Final = (PENDING, RUNNING, SUCCEEDED, FAILED, SUPERSEDED)

# A solve is in flight while it is in one of these. The partial unique index is what holds
# the single-flight invariant, so this pair is read by the schema rather than by a service.
NON_TERMINAL_STATUSES: Final = (PENDING, RUNNING)
TERMINAL_STATUSES: Final = (SUCCEEDED, FAILED, SUPERSEDED)

# The first attempt is 1, so `attempt` reads as "this is try 3 of N" on the wire rather
# than needing the reader to add one.
FIRST_ATTEMPT = 1

ERROR_CODE_MAX_LENGTH = 64
