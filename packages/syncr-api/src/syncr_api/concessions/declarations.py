"""What a caller asks for, as a value the service reads rather than a request body.

One field pair, and it is deliberately all the wire carries: the kind of concession and the target
it acts on. The figures -- how much of a floor to breach, which nights to shorten and by how much --
come from the enumeration over that week's own verdict, so a caller cannot ask for a concession
syncr did not offer.

The alternative was a body carrying the figures. It would let a client reduce a routine below the
minimum the user set, breach a floor by more than it reserves, or concede something on a week that
is not short at all, and every one of those would have to be re-validated here against the same
enumeration anyway.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from syncr_domain.plan import AdjustmentKind


@dataclass(frozen=True, slots=True)
class RequestedConcession:
    """The concession a caller asked to be solved against: a kind, and what it acts on."""

    kind: AdjustmentKind
    target_id: UUID
