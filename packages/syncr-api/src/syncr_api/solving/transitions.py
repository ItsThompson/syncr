"""The operation state machine: which transitions exist, and which states are the end.

Pure, and stated as one table rather than as a rule per writer. The lifecycle has four writers
already -- a request that performs its own work inline, the worker's terminal transitions, the
retry, and the reaper -- and a fifth arrives with the solve coordinator. A machine each of them
carried its own reading of is a machine that holds until two of them disagree.

```
   create              claim               commit
  ──────▶ pending ──────────▶ running ──┬──────▶ succeeded
             │                          │
             │ replaced by an           ├──────▶ superseded
             │ immediate re-solve       │
             ▼                          └──────▶ failed
        superseded                               │
                                                 │ attempt < max
                                                 ▼
                                              pending
```

**There is no ``running`` to ``pending`` edge, and the reaper does not need one.** A worker that
died mid-solve leaves its operation ``running`` past its lease, and the honest reading of that is
a failure whose cause is the lease rather than a state of its own: the work did not complete and
nobody knows why. So the reaper finishes such an operation as ``failed``, and the ONE retry rule
below decides whether it comes back. Two consequences fall out rather than being arranged. The
attempt bound applies to a dying worker exactly as it applies to a raising solver, so an operation
no worker can survive stops retrying instead of looping forever. And there is one place that
increments ``attempt``.

**Terminality is a function of the status AND the attempt.** ``failed`` is the only status whose
terminality is not decided by the word alone, which is why the retention window it belongs to is
read from :func:`is_terminal` rather than from a status comparison.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from syncr_api.solving.config import (
    FAILED,
    MAX_ATTEMPTS,
    PENDING,
    RUNNING,
    SUCCEEDED,
    SUPERSEDED,
    OperationStatus,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

# Every transition that exists, keyed by the status it leaves. A status whose set is empty is
# terminal by the word alone; `failed` leaves to `pending` while the attempt budget allows, which
# `may_retry` decides and this table does not.
LEGAL_TRANSITIONS: Final[Mapping[OperationStatus, frozenset[OperationStatus]]] = {
    PENDING: frozenset({RUNNING, SUPERSEDED}),
    RUNNING: frozenset({SUCCEEDED, SUPERSEDED, FAILED}),
    FAILED: frozenset({PENDING}),
    SUCCEEDED: frozenset(),
    SUPERSEDED: frozenset(),
}


def may_transition(*, at_status: OperationStatus, to: OperationStatus) -> bool:
    """Whether an operation in ``at_status`` may become ``to``."""
    return to in LEGAL_TRANSITIONS[at_status]


def statuses_that_may_become(status: OperationStatus) -> frozenset[OperationStatus]:
    """Every status an operation may be in for ``status`` to be its next one.

    The table read backwards, derived from the forward statement rather than written out, so the
    two cannot drift. What reads it is the ``WHERE`` clause of each transition's own statement: the
    legality is then part of the write rather than a check performed before one, so two workers
    racing on one row cannot both pass the check and both write.
    """
    return frozenset(
        leaving for leaving, reachable in LEGAL_TRANSITIONS.items() if status in reachable
    )


def may_retry(*, status: OperationStatus, attempt: int, max_attempts: int = MAX_ATTEMPTS) -> bool:
    """Whether a failed operation has an attempt left.

    The attempt count is one-based, so the third attempt of three is the last: a fourth would be
    ``attempt`` 4, which is past the bound.
    """
    return status == FAILED and attempt < max_attempts


def is_terminal(*, status: OperationStatus, attempt: int, max_attempts: int = MAX_ATTEMPTS) -> bool:
    """Whether this operation will never change again.

    ``succeeded`` and ``superseded`` are terminal by the word. ``failed`` is terminal only once
    the attempts are spent, which is why the retention sweep reads this rather than the status.
    """
    if status in {SUCCEEDED, SUPERSEDED}:
        return True
    return status == FAILED and not may_retry(
        status=status, attempt=attempt, max_attempts=max_attempts
    )
