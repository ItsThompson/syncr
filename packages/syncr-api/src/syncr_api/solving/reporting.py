"""What each status means to the user: one word, and one sentence per word.

``superseded`` must be reported distinctly from ``failed``, and this is where that is true rather
than asserted. Supersession is the expected outcome of editing quickly, so presenting it as a
failure would make normal use look broken: the word differs, and so does the sentence, which says
that a follow-up is already running and that nothing is wrong.

Every sentence names what still works, which is the same rule the api's error details and the
in-product degradation notices follow. A failed solve leaves the previous live plan untouched and
still projected, and saying only that the solve failed would leave the user believing they have no
plan.

The table is total over the five statuses and a test asserts the five sentences are distinct, so a
status added to the vocabulary reaches the wire with a statement of its own rather than borrowing
one that describes a different state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from syncr_api.solving.config import (
    FAILED,
    PENDING,
    RUNNING,
    SUCCEEDED,
    SUPERSEDED,
    OperationStatus,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

STATEMENT_BY_STATUS: Final[Mapping[OperationStatus, str]] = {
    PENDING: (
        "This work is scheduled and has not started. The plan you are looking at is the one "
        "before it, and it is still projected."
    ),
    RUNNING: (
        "This work is under way. The plan you are looking at is the one before it, and it is "
        "still projected."
    ),
    SUCCEEDED: "This work completed and its result was adopted, so the plan is current.",
    SUPERSEDED: (
        "A later change of your own displaced this work, so its result was discarded and a "
        "follow-up is already running. Nothing went wrong and nothing was lost."
    ),
    FAILED: (
        "This work could not complete. The previous plan for the week is untouched and still "
        "projected, so nothing was lost; the plan simply predates your latest changes."
    ),
}


def statement(status: OperationStatus) -> str:
    """The one sentence this status renders as, naming what still works."""
    return STATEMENT_BY_STATUS[status]
