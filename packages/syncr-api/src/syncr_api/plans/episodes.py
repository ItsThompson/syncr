"""The episode: the unit the early-catch product metric counts, and nothing that counts them.

One infeasibility deliberately produces two or three rows. A pin's probe finds a gap, the debounced
solve confirms it, and the maintainer's next tick may record its close, so a formula counting rows
tops out near 0.5 under perfect behaviour against a target of 0.8. The unit is therefore the
episode:

```
An INFEASIBILITY EPISODE for a week runs from a transition to feasible = false
until the next transition to feasible = true, or past the end of the period if it
never closes.

  numerator     episodes whose FIRST row has session_mode_active = true
  denominator   every episode that BEGAN in the period
  excluded      provenance-only rows. They are diagnostic, not discoveries
```

The first row is the discovery and everything after it is confirmation, which is why
:attr:`Episode.caught_early` reads that row and no other.

**This module defines an episode and computes no ratio.** The metric job that reads a period across
every week, applies the numerator and the denominator, and exports
``syncr_infeasibility_caught_early_ratio`` is ticket 54's. What lives here is the grouping both it
and a retro read, so there is one definition rather than one per consumer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import datetime

    from syncr_api.plans.records import VerdictEventRecord


@dataclass(frozen=True, slots=True, kw_only=True)
class Episode:
    """One span of a week being reported impossible, and the row that discovered it."""

    first: VerdictEventRecord
    confirmations: tuple[VerdictEventRecord, ...] = ()
    closed_by: VerdictEventRecord | None = None

    @property
    def began_at(self) -> datetime:
        """When the week was first reported unable to hold its commitments."""
        return self.first.occurred_at

    @property
    def ended_at(self) -> datetime | None:
        """When it was next reported able to, or ``None`` while it is still open."""
        return None if self.closed_by is None else self.closed_by.occurred_at

    @property
    def is_open(self) -> bool:
        """Whether this week has not yet been reported able to hold its commitments again."""
        return self.closed_by is None

    @property
    def caught_early(self) -> bool:
        """Whether the discovery happened while the weekly session was open. ``VE9``.

        The FIRST row decides it. A session transition confirmed by the worker an instant later
        carries ``session_mode_active = false`` on the confirming row, because the worker cannot
        know whether the session is open, so reading any row but the first would report a catch as a
        miss.
        """
        return self.first.session_mode_active


def episodes(recorded: Sequence[VerdictEventRecord]) -> tuple[Episode, ...]:
    """The episodes a week's transitions describe, oldest first.

    ``recorded`` is one week's rows in the order they occurred, which is what
    :meth:`~syncr_api.plans.verdict_events.VerdictEventRepository.for_week` answers with. Rows for
    several weeks are not one series: a week is the scope an episode is defined over, so a caller
    holding a period groups by week first.

    A row reporting the week feasible while no episode is open closes nothing and opens nothing: the
    first verdict a mutation records for a healthy week is exactly that, and the metric must not
    read it as a discovery.
    """
    closed: list[Episode] = []
    open_rows: list[VerdictEventRecord] = []
    for row in recorded:
        if not row.feasible:
            open_rows.append(row)
            continue
        if open_rows:
            closed.append(_episode(open_rows, closed_by=row))
            open_rows = []
    if open_rows:
        closed.append(_episode(open_rows, closed_by=None))
    return tuple(closed)


def caught_early_ratio(counted: Iterable[Episode]) -> float | None:
    """The share of episodes discovered during a weekly session, or ``None`` when there were none.

    ``None`` rather than zero for an empty period, because a period with no infeasibility is not a
    period in which none was caught: a gauge set to zero for it would read as total failure of the
    thing being measured. The job that exports the gauge decides what to publish for that case.
    """
    episodes_counted = list(counted)
    if not episodes_counted:
        return None
    return sum(one.caught_early for one in episodes_counted) / len(episodes_counted)


def _episode(rows: list[VerdictEventRecord], *, closed_by: VerdictEventRecord | None) -> Episode:
    first, *confirmations = rows
    return Episode(first=first, confirmations=tuple(confirmations), closed_by=closed_by)
