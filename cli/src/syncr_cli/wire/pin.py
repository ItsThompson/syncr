"""What one edit answers with: the pin it created, the verdict as of that edit, and the next solve.

``block move`` is the CLI's one mutation that changes where work sits, so it is the one that reports
a verdict computed without waiting for anything. The verdict is the capacity probe's, and its
provenance says so: arithmetic can prove a week impossible and cannot prove one possible.

The operation is the solve the edit asked for, due one debounce window later, or the one already in
flight that this edit joined. It is reported so a caller can follow it without guessing an
identifier, and it does not decide this command's exit code: the pin is what was asked for and the
verdict is what it cost.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from syncr_cli.wire.operation import Operation
from syncr_cli.wire.reading import JsonMapping, mapping, nested, span, text
from syncr_cli.wire.verdict import Verdict

if TYPE_CHECKING:
    from syncr_domain.intervals import Interval

PINNED_PATH = "pinned"


@dataclass(frozen=True, slots=True)
class Pinned:
    """One edit: where the user put a block, where the solver had it, and what follows."""

    pin_id: str
    iso_week: str
    block_id: str
    interval: Interval
    superseded_placement: Interval
    verdict: Verdict
    operation: Operation
    payload: JsonMapping

    @classmethod
    def read(cls, body: object) -> Self:
        payload = mapping(body, PINNED_PATH)
        pin = nested(payload, "pin", PINNED_PATH)
        where = f"{PINNED_PATH}.pin"
        return cls(
            pin_id=text(pin, "id", where),
            iso_week=text(pin, "isoWeek", where),
            block_id=text(pin, "blockId", where),
            interval=span(pin, "interval", where),
            superseded_placement=span(pin, "supersededPlacement", where),
            verdict=Verdict.read(nested(payload, "verdict", PINNED_PATH), f"{PINNED_PATH}.verdict"),
            operation=Operation.read(
                nested(payload, "operation", PINNED_PATH), f"{PINNED_PATH}.operation"
            ),
            payload=payload,
        )
