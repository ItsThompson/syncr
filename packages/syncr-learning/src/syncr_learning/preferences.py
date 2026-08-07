"""Which edits can rank a pair, and how many cannot because the corpus predates the measurement.

Split from :mod:`syncr_learning.features` because it reads a different table for a different reason:
the four block-derived observations come from the outcome log, and this comes from the edit events,
which are the only pairwise-labelled rows the product has.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_learning.config import OBJECTIVE_TERMS
from syncr_learning.exclusions import is_off_plan
from syncr_learning.observations import RankExample

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from syncr_learning.facts import OffPlanSpan, RecordedEdit


def rank_examples(
    edits: Sequence[RecordedEdit], off_plan: Sequence[OffPlanSpan]
) -> Iterable[RankExample]:
    """Every edit that can rank a pair: on-plan, and carrying the difference it is ranked on.

    Excluded on three grounds. E4's flag, which the row itself carries. An accepted placement inside
    a span declared SINCE the edit, which an older row's flag cannot know about, so both are checked
    and either excludes. And an absent or malformed measurement difference, which is every row
    written before the difference was measured at all: :func:`unmeasured` counts those.

    A degenerate pair -- two identical placements, so every difference is zero -- is kept here and
    refused by the fit. The sample count that decides the gate is taken there, so a pair that
    expresses no preference has to reach it to be excluded from it.
    """
    for edit in edits:
        if _is_excluded(edit, off_plan) or not _carries_the_seven(edit):
            continue
        yield RankExample(difference=dict(edit.measurement_delta or {}))


def unmeasured(edits: Sequence[RecordedEdit], off_plan: Sequence[OffPlanSpan]) -> int:
    """How many otherwise-countable edits carry no usable measurement difference.

    Exported as a metric rather than logged and forgotten. These are the rows written before the
    difference was recorded, E5 forbids pruning them, and the figure is what says whether a weight
    gate is being held back by history rather than by a quiet user.
    """
    return sum(
        1 for edit in edits if not _is_excluded(edit, off_plan) and not _carries_the_seven(edit)
    )


def _is_excluded(edit: RecordedEdit, off_plan: Sequence[OffPlanSpan]) -> bool:
    return edit.inside_off_plan or is_off_plan(edit.accepted, off_plan)


def _carries_the_seven(edit: RecordedEdit) -> bool:
    """Whether this row's difference names the objective's seven terms, no more and no fewer.

    Checked rather than trusted, because a row is permanent and the objective's vocabulary is not: a
    term added to the objective makes every earlier row six-of-seven, and a fit over a mixture would
    rank some pairs on a term it read as absent from others.
    """
    return edit.measurement_delta is not None and set(edit.measurement_delta) == set(
        OBJECTIVE_TERMS
    )
