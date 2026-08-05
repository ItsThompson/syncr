"""The three renderings of a duration, and which surface each belongs to.

``--json`` carries integer minutes and never a formatted string, so every one of these is a
human rendering only.

| Rendering | Where | Why that one |
|---|---|---|
| ``1h20m`` | a verdict's headline and a shortfall's sentence | The product's one wording
for a duration in prose, owned by the domain |
| ``150m`` | the ledger's duration column | Right-aligned minutes are comparable by eye down a
column, which is the point of a monospace ledger |
| ``80.8h`` | the summary strip | The strip compares magnitudes across a week, and ``4848m``
compares nothing |

The domain owns the first, so it is imported rather than restated here.
"""

from __future__ import annotations

from typing import Final

from syncr_domain.budgets import MINUTES_PER_HOUR

# The ledger's duration column, wide enough for three digits and the unit. A column that grew
# with the week's longest block would reshuffle every line of a diff when one block changed, so
# it is fixed and widens only for a value that cannot fit.
DURATION_COLUMN_WIDTH: Final = 4


def minutes_cell(minutes: int, width: int = DURATION_COLUMN_WIDTH) -> str:
    """One duration as the ledger's column holds it: right-aligned integer minutes."""
    return f"{minutes}m".rjust(width)


def hours_tenths(minutes: int) -> str:
    """One duration as the summary strip holds it: hours to a tenth."""
    return f"{minutes / MINUTES_PER_HOUR:.1f}h"


def duration_column_width(durations: list[int]) -> int:
    """How wide the duration column has to be for these values.

    Never narrower than the fixed width, so an ordinary week renders identically whatever it
    holds, and wide enough for an off-plan day that a fixed column could not.
    """
    if not durations:
        return DURATION_COLUMN_WIDTH
    return max(DURATION_COLUMN_WIDTH, max(len(f"{minutes}m") for minutes in durations))
