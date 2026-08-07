"""What the three ``block`` and ``plan approve`` mutations answer with, in both renderings.

Three shapes, one subject: what a write to the plan just did. Each answers with the resource as the
api now holds it, so a caller reads what it wrote rather than what it sent.

**The verdict and the operation are placed by the shared renderer, not here.** ``block move``
answers with a verdict computed from capacity arithmetic and with the solve the edit asked for, and
``plan approve`` answers with the projection it queued; both travel on the result rather than in
these lines, which is what stops two commands laying a verdict out differently.

**An instant is printed as the instant it is.** None of these payloads carries a zone map, so naming
a wall time would state one in a zone the surface cannot speak for.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from syncr_cli.rendering.human import iso_deadline
from syncr_cli.rendering.views import PlainView

if TYPE_CHECKING:
    from syncr_cli.wire.approval import WeekApproved
    from syncr_cli.wire.day import Outcome
    from syncr_cli.wire.pin import Pinned
    from syncr_cli.wire.reading import JsonMapping

_LABEL: Final = 10

# What separates the two halves of a move, in words rather than an arrow: an arrow in a monospace
# ledger reads as two characters of punctuation and this reads as what happened.
INSTEAD_OF: Final = "instead of"


@dataclass(frozen=True, slots=True)
class OutcomeRecordedView(PlainView):
    """What ``block done``, ``block skip``, and ``block partial`` answer with."""

    outcome: Outcome

    @property
    def payload(self) -> JsonMapping:
        return self.outcome.payload

    def header_lines(self) -> list[str]:
        return [
            f"{'recorded':<{_LABEL}} {self.outcome.statement}",
            f"{'block':<{_LABEL}} {self.outcome.block_id}",
            f"{'scheduled':<{_LABEL}} {iso_deadline(self.outcome.occurred_at)}",
            f"{'day':<{_LABEL}} "
            + (
                "unconfirmed, so it is excluded from reviews and from learning"
                if self.outcome.confirmed_at is None
                else f"confirmed at {iso_deadline(self.outcome.confirmed_at)}"
            ),
        ]


@dataclass(frozen=True, slots=True)
class BlockMovedView(PlainView):
    """What ``block move`` answers with: the pin it created, and what it displaced."""

    pinned: Pinned

    @property
    def payload(self) -> JsonMapping:
        return self.pinned.payload

    def header_lines(self) -> list[str]:
        return [
            f"{'pinned':<{_LABEL}} {self.pinned.block_id} in {self.pinned.iso_week}",
            f"{'to':<{_LABEL}} {iso_deadline(self.pinned.interval.start)}",
            f"{INSTEAD_OF:<{_LABEL}} {iso_deadline(self.pinned.superseded_placement.start)}",
            f"{'pin':<{_LABEL}} {self.pinned.pin_id}",
        ]


@dataclass(frozen=True, slots=True)
class WeekApprovedView(PlainView):
    """What ``plan approve`` answers with: the revision it appended, permanently."""

    approved: WeekApproved

    @property
    def payload(self) -> JsonMapping:
        return self.approved.payload

    def header_lines(self) -> list[str]:
        lines = [
            f"{'approved':<{_LABEL}} {self.approved.iso_week}    {self.approved.reason}",
            f"{'revision':<{_LABEL}} {self.approved.revision_id}",
            f"{'version':<{_LABEL}} {self.approved.input_version}, "
            f"solved against {self.approved.solved_against_version}",
        ]
        if self.approved.was_solved_against_an_older_week:
            lines.append(
                f"{'note':<{_LABEL}} the week moved on while this proposal waited, which is "
                "permitted: the next solve proposes any correction"
            )
        if self.approved.adjustment_label is not None:
            lines.append(f"{'concession':<{_LABEL}} {self.approved.adjustment_label}")
        return lines
