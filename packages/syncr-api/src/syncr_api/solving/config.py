"""The vocabularies the ``operations`` table is defined against.

The status set is a state machine, and which members are TERMINAL is what the two indexes
and the retention rule are stated over: at most one non-terminal solve exists per week, and
only terminal rows are ever pruned.

``superseded`` is terminal and is NOT an error. It is the expected outcome of editing
quickly: the user's own later change displaced a solve, and a follow-up is already running.
Presenting it as a failure would make normal use look broken.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final, Literal

from syncr_api.core.settings import API_PREFIX

OPERATIONS_TABLE = "operations"

# `/api/v1/operations`, built from the versioned prefix rather than written out.
OPERATIONS_PREFIX: Final = f"{API_PREFIX}/operations"
# Relative to the router's prefix.
OPERATION_PATH: Final = "/{operation_id}"

OPERATION_RESOURCE: Final = "operation"

type OperationKind = Literal["solve", "materialize", "calendar_sync", "projection"]
SOLVE: Final[OperationKind] = "solve"
MATERIALIZE: Final[OperationKind] = "materialize"
CALENDAR_SYNC: Final[OperationKind] = "calendar_sync"
PROJECTION: Final[OperationKind] = "projection"
OPERATION_KINDS: Final = (SOLVE, MATERIALIZE, CALENDAR_SYNC, PROJECTION)

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

# How many attempts one operation gets before it fails terminally. A solve is budgeted at under
# two seconds, so three attempts spend at most six seconds of worker time, and a fault that
# survives three of them is not the transient one a retry exists for. The count is visible on the
# wire, so a retrying job is not silent.
MAX_ATTEMPTS: Final = 3

# How long the next attempt waits, doubling per attempt already spent. A solver fault is not
# cleared by retrying immediately, and the week has nothing waiting on it: the previous live plan
# is untouched and still projected while the retries run.
RETRY_BACKOFF: Final = timedelta(seconds=30)

# How long a claim is good for. Sixty times the two-second solve budget, so a slow solve is never
# reaped mid-flight, and short enough that a worker killed between two ticks has its operation
# retried within a quarter hour rather than at the next deploy. Read against `started_at` rather
# than stored as an expiry, because the length is a property of the deployment and not of the row.
LEASE: Final = timedelta(minutes=2)

# How long a terminal operation is kept. Operations are telemetry rather than facts about the
# plan -- the plan's history is `plan_revisions`, which is never pruned -- so pruning one loses
# nothing about what the plan was. A failure is kept three times as long because it is
# diagnostic: its `failed_input_snapshot` is what reproduces the failure locally.
SUCCEEDED_RETENTION: Final = timedelta(days=30)
FAILED_RETENTION: Final = timedelta(days=90)

# How many operations one page of the list route holds. A week appends a handful and a burst of
# edits appends one, so the default covers a day of ordinary use without a caller stating a number.
PAGE_LIMIT_DEFAULT: Final = 50
PAGE_LIMIT_MAX: Final = 200

ERROR_CODE_MAX_LENGTH = 64

# What a reaped operation's failure is called. A worker that died mid-solve reports nothing, so the
# cause is the lease rather than anything the solve said.
LEASE_EXPIRED: Final = "lease_expired"
