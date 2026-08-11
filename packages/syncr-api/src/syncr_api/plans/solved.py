"""Whether a week's plan of record holds anything a solve chose to put there.

A week acquires a plan by two different routes, and the documents they produce are not
interchangeable. The horizon maintainer and the fallback after a terminal failure both
MATERIALIZE: the frame, the imported commitments, the buffers those cast, each day's concrete
entries, and an empty slot wherever content was left to be chosen. A solve then binds content into
those slots, and the blocks it adds are the only ones anybody decided the time of.

``syncr_domain.identity.PLACED_BY`` splits the seven origins by exactly that question, and this
module is stated over one half of the split, so the set is the domain's rather than a second
enumeration that could drift:

| Where the block's time came from | Held here to be a solve's |
|---|---|
| the solve chose it out of the time that was free: a habit, a task | **yes** |
| its source fixed it: a routine, a concrete entry, a commitment, a buffer | no |

**A materialized plan and no plan at all answer the same way**, which is the point of asking the
question about the document rather than about the revision: a week the maintainer reached and a week
it has not both hold nothing a solve placed, and anything reading this treats them alike.

**A week whose solve placed nothing also answers no**, and that is deliberate rather than an
oversight. What the answer is about is whether a solve's own choices are there to be read, not
whether a solve has run: a solve that bound no content left none.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_domain.identity import is_placed_by_the_solver

if TYPE_CHECKING:
    from syncr_domain.plan import PlanDocument


def holds_a_solver_placed_block(live: PlanDocument | None) -> bool:
    """Whether ``live`` holds at least one block a solve chose the time of."""
    if live is None:
        return False
    return any(is_placed_by_the_solver(block.origin) for block in live.blocks)
