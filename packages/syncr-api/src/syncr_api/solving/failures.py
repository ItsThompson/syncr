"""Why a solve failed: the closed set of causes, and one sentence per cause.

``Operation.error`` is a code plus a message, and the message's rule is the one every degradation
notice in this product follows: it names what still works. A solve that failed leaves the previous
live plan untouched and still projected, so a message saying only that the solve failed would leave
the user believing they have no plan at all.

The four causes are the four places a solve can stop, and they are distinguished because the answer
differs: unreadable inputs and a refused write are faults to investigate, a raising solver is what
the retry exists for, and a past disagreement is a statement about what the week already lived.

The table is total over the vocabulary and a test asserts the sentences are distinct, so a cause
added later reaches the operation with a statement of its own rather than borrowing one that
describes something else.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from syncr_api.solving.config import (
    INPUTS_UNREADABLE,
    PAST_DISAGREEMENT,
    SOLVER_RAISED,
    WRITE_REFUSED,
    SolveFailure,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

_STILL_PROJECTED = (
    "The previous plan for this week is untouched and still projected, and your calendar is "
    "unchanged."
)

STATEMENT_BY_CAUSE: Final[Mapping[SolveFailure, str]] = {
    INPUTS_UNREADABLE: (
        f"syncr could not read everything this week's plan is built from, so no plan was "
        f"produced. {_STILL_PROJECTED} Nothing you have declared was changed."
    ),
    SOLVER_RAISED: (
        f"The solve itself could not complete, so no plan was produced. {_STILL_PROJECTED} It "
        "will be tried again shortly."
    ),
    PAST_DISAGREEMENT: (
        f"The plan this solve produced places time the week has already lived differently than "
        f"the week recorded it, so it was refused rather than adopted. {_STILL_PROJECTED}"
    ),
    WRITE_REFUSED: (
        f"The plan this solve produced could not be recorded, so none of it was. {_STILL_PROJECTED}"
    ),
}


def statement_for(cause: SolveFailure) -> str:
    """The one sentence this cause renders as, naming what still works."""
    return STATEMENT_BY_CAUSE[cause]
