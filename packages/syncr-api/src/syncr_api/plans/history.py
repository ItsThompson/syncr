"""One page of a week's revision history: what each row auto-applied, and what it was conceded.

A revision row states its status and the reason it exists, and two of the history's obligations are
not answerable from the row alone.

**What auto-applied is a difference between two revisions.** An ``applied`` revision is one the
authority rule let through, which by that rule is a candidate that filled empty space and did
nothing else, so the blocks it holds that its predecessor did not ARE what applied without asking.
The reason column says which rule let it through and cannot say which block: naming the block needs
the revision before it, and a history read already holds both.

**The concessions a plan was solved under are named by identifier in the document.** So the week's
concession rows are read once and paired here, rather than a route resolving one per revision.

A concession the week no longer holds under that identifier is COUNTED rather than dropped. Two
things produce one, and both leave the document naming a row that is not there: a revocation, which
deletes it, and a later concession of the same kind and target, which replaces it and keeps the
replaced row's own identifier. Either way a history that dropped it silently would report a plan as
solved under fewer concessions than it was.

Pure, and every document is rebuilt exactly once, so a page of fifty is fifty rebuilds rather than
one per question asked of it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.plans.config import APPLIED
from syncr_api.plans.stored_documents import plan_document
from syncr_api.plans.week_views import WeekRevision, WeekRevisions

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from uuid import UUID

    from syncr_api.plans.records import PlanRevisionRecord, WeekAdjustmentRecord
    from syncr_domain.plan import PlanDocument


def revision_page(
    found: Sequence[PlanRevisionRecord],
    *,
    held: Sequence[WeekAdjustmentRecord],
    page: int,
) -> WeekRevisions:
    """One page of ``found``, newest first, bounded by ``page``.

    ``found`` carries one row more than the page when the week holds more, which is what makes the
    truncation measured rather than guessed AND what gives the oldest row on the page the
    predecessor it needs. So the extra row is read twice: once to answer whether the history is
    complete, and once as the plan the last shown revision changed.
    """
    documents = [plan_document(one.document) for one in found]
    by_id = {one.id: one for one in held}
    return WeekRevisions(
        revisions=tuple(
            WeekRevision(
                record=record,
                auto_applied=_auto_applied(
                    record, documents[position], _predecessor(documents, position)
                ),
                adjustments=_named(documents[position], by_id),
                unnamed_adjustments=_not_held(documents[position], by_id),
            )
            for position, record in enumerate(found[:page])
        ),
        truncated=len(found) > page,
    )


def _predecessor(documents: Sequence[PlanDocument], position: int) -> PlanDocument | None:
    """The plan this revision replaced, or ``None`` when the page cannot see it.

    The history is newest first, so a revision's predecessor is the row after it. The oldest row of
    a truncated page has one and the oldest row of a complete page does not, because there is none:
    it is the first plan the week ever had.
    """
    following = position + 1
    return documents[following] if following < len(documents) else None


def _auto_applied(
    record: PlanRevisionRecord, document: PlanDocument, previous: PlanDocument | None
) -> tuple[str, ...]:
    """What this revision added without being asked, by title, in the document's own order.

    Empty for an ``approved`` revision, whose changes are the ones the user assented to, and empty
    for the first plan a week ever had, which added everything and asked about nothing: the reason
    column already says the maintainer produced it, and listing a whole week's blocks as a change
    would say nothing a reader can use.
    """
    if record.status != APPLIED or previous is None:
        return ()
    held = previous.blocks_by_id()
    return tuple(block.title for block in document.blocks if block.id not in held)


def _named(
    document: PlanDocument, by_id: Mapping[UUID, WeekAdjustmentRecord]
) -> tuple[WeekAdjustmentRecord, ...]:
    """The concessions this plan was solved under that the week still holds, in the stored order."""
    under = set(document.adjustments)
    return tuple(one for one in by_id.values() if one.id in under)


def _not_held(document: PlanDocument, by_id: Mapping[UUID, WeekAdjustmentRecord]) -> int:
    """How many of them the week no longer holds under that identifier: revoked, or replaced."""
    return sum(1 for one in document.adjustments if one not in by_id)
