"""What a caller states when it pins a block, and when it rejects one proposed move.

Two values rather than loose arguments, and the second carries less than the first for a reason that
is the whole of the rule: rejecting a proposed move is pinning the block where it already is,
so the caller names the block and nothing else. The interval comes from the plan of record, which is
the only definition of "where it already is" that a client cannot get wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_domain.identity import BlockId


@dataclass(frozen=True, slots=True, kw_only=True)
class PinRequested:
    """One drag, or one keyboard move, or the ``p`` toggle: this block, starting here.

    The duration is absent because a drag does not resize: the block keeps the length the plan gave
    it, so the accepted interval is derived from the block rather than stated by the caller. A
    caller that could state one could state a different one, and a pin is a training label.
    """

    block_id: BlockId
    start: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class BlockRejected:
    """One proposed move the user refuses, named by the block it would move."""

    block_id: BlockId
