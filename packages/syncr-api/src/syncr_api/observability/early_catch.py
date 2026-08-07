"""The early-catch ratio over a period: episodes counted, not rows.

:mod:`syncr_api.plans.episodes` defines an episode and the ratio over a set of them. What it
deliberately does not do is decide which episodes a period holds, because that needs every week's
rows and a period boundary. This is that half.

## Why a row cannot be the unit, stated where the ratio is computed

One infeasibility deliberately emits two to three rows. A pin's probe finds a gap and records one;
the debounced solve confirms the same gap and records a second, because the provenance changed while
the week was still infeasible; the maintainer's tick may later record the close. Trace one
infeasibility caught perfectly during a weekly session:

```
 t0  user pins        probe  -> infeasible   row A  surface=pin    session=TRUE
 t1  debounced solve  solver -> infeasible   row B  surface=solve  session=false

 COUNTING ROWS      numerator 1, denominator 2   ->  0.50
 COUNTING EPISODES  one episode, first row is A  ->  1.00
```

The target is 80%. A row-counting formula therefore tops out near 0.5 under **perfect** behaviour,
and three further contributions push it lower: the worker supplies ``session_mode_active = false``
on row B because it cannot know whether the session is open, the maintainer's periodic probe adds a
provenance flip, and only genuine mid-week discovery is a real denominator entry. So the unit is the
episode, and the provenance-only rows that confirm one are excluded from both halves of the ratio.

## The period bounds when an episode BEGAN, not which rows are read

A week's whole history is read, because whether a ``feasible = false`` row opens an episode or
confirms one already open is decided by the rows before it, including rows older than the period.
The period then selects episodes by the instant they began, which is what makes an episode still
open at the boundary count exactly once, in the period it began.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.plans.episodes import caught_early_ratio, episodes

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_api.plans.episodes import Episode
    from syncr_api.plans.records import VerdictEventRecord
    from syncr_domain.intervals import Interval
    from syncr_domain.weeks import IsoWeek


def episodes_beginning_in(
    history_by_week: Mapping[IsoWeek, Sequence[VerdictEventRecord]], *, period: Interval
) -> tuple[Episode, ...]:
    """Every episode that began inside ``period``, over each week's full history.

    Grouped by week first, because a week is the scope an episode is defined over: rows for several
    weeks interleaved would read one week's recovery as another week's close.
    """
    return tuple(
        episode
        for iso_week in sorted(history_by_week, key=str)
        for episode in episodes(history_by_week[iso_week])
        if period.start <= episode.began_at < period.end
    )


def caught_early_over(
    history_by_week: Mapping[IsoWeek, Sequence[VerdictEventRecord]], *, period: Interval
) -> float | None:
    """The share of this period's episodes discovered during a weekly session.

    ``None`` for a period that held no episode, which is not the same as a period in which none was
    caught: a gauge set to zero for it would read as total failure of the thing being measured.
    """
    return caught_early_ratio(episodes_beginning_in(history_by_week, period=period))
