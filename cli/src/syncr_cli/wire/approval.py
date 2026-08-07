"""What one approval wrote: the revision, the two versions, and the projection it queued.

**Both versions are on it, and the pair is the point.** ``inputVersion`` is what the week holds now,
after this approval bumped it; ``solvedAgainstVersion`` is the input state the approved plan was
produced from. They differ exactly when the week moved on between the solve and the approval, which
is permitted, and a caller can see it rather than having to infer it.

The projection is the operation this approval dispatched, which is what writes the approved week to
the user's calendar. It is printed so a caller can follow it, and it does not decide the exit code:
the approval succeeded whatever the projection then does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from syncr_cli.wire.operation import Operation
from syncr_cli.wire.reading import (
    JsonMapping,
    instant,
    integer,
    mapping,
    nested,
    optional_nested,
    text,
)

if TYPE_CHECKING:
    from datetime import datetime

APPROVED_PATH = "approved"


@dataclass(frozen=True, slots=True)
class WeekApproved:
    """What one approval did, and everything two renderings need to say so."""

    revision_id: str
    iso_week: str
    reason: str
    approved_at: datetime
    input_version: int
    solved_against_version: int
    adjustment_label: str | None
    projection: Operation
    payload: JsonMapping

    @classmethod
    def read(cls, body: object) -> Self:
        payload = mapping(body, APPROVED_PATH)
        adjustment = optional_nested(payload, "adjustment", APPROVED_PATH)
        return cls(
            revision_id=text(payload, "revisionId", APPROVED_PATH),
            iso_week=text(payload, "isoWeek", APPROVED_PATH),
            reason=text(payload, "reason", APPROVED_PATH),
            approved_at=instant(payload, "approvedAt", APPROVED_PATH),
            input_version=integer(payload, "inputVersion", APPROVED_PATH),
            solved_against_version=integer(payload, "solvedAgainstVersion", APPROVED_PATH),
            adjustment_label=(
                None
                if adjustment is None
                else text(adjustment, "label", f"{APPROVED_PATH}.adjustment")
            ),
            projection=Operation.read(
                nested(payload, "projection", APPROVED_PATH), f"{APPROVED_PATH}.projection"
            ),
            payload=payload,
        )

    @property
    def was_solved_against_an_older_week(self) -> bool:
        """Whether the week moved on while this proposal waited.

        The approval's own bump is one, so a gap wider than that is a real divergence rather than
        the bump this write just made.
        """
        return self.input_version - self.solved_against_version > 1
