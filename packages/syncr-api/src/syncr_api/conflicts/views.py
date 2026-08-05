"""What the resolution answers with: the conflict as it now stands, and the solve that reads it.

Two fields rather than one, because the answer to "what did answering this do" is both: the record
is permanent and the operation is the pass that will act on it. The operation is ``None`` for the
one answer that asks for no pass, which is what makes "nothing else changed" visible on the wire
rather than something a client has to know.

Here rather than in the wire schema for the reason every other service's value shapes are: the
schema describes what crosses the boundary, and a service answers with values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syncr_api.plans.records import ConflictRecord
    from syncr_api.solving.records import OperationRecord


@dataclass(frozen=True, slots=True)
class Resolved:
    """One answered conflict, and the solve that will read the answer if one was asked for."""

    conflict: ConflictRecord
    operation: OperationRecord | None
