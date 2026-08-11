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

A concession the week no longer holds under that identifier is COUNTED rather than dropped, and the
count says which of two things happened, because they are different facts about the week.

**A revocation deletes the row**, so the concession applies to nothing any more.

**A later approval for the same kind and target REPLACES it**, and that write keeps the replaced
row's identifier: the document appended beside a replacement names the candidate identifier the row
did not take, so the concession is still in force under a name this revision does not use.

Which of the two is read off the rows the week still holds. A replacement rewrites everything about
a row except its identity, so it leaves a row carrying an identifier some earlier revision already
named, stamped with the replacing approval's own instant. An insert cannot leave that: its
identifier is minted for the approval that appends the revision naming it, so nothing older can name
it. So a row older than the write that last set its figures is a replaced concession, and the
revision whose instant that row bears is the one left unable to name it.

The two sum to what the single count used to be, so a plan is still never reported as solved under
fewer concessions than it was.

Pure, and every document is rebuilt exactly once, so a page of fifty is fifty rebuilds rather than
one per question asked of it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.plans.config import APPLIED
from syncr_api.plans.stored_documents import plan_document
from syncr_api.plans.week_views import UnnamedConcessions, WeekRevision, WeekRevisions

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
    taken_over = _identities_older_than_their_row(found, documents, held)
    return WeekRevisions(
        revisions=tuple(
            WeekRevision(
                record=record,
                auto_applied=_auto_applied(
                    record, documents[position], _predecessor(documents, position)
                ),
                adjustments=_named(documents[position], by_id),
                unnamed=_unnamed(record, documents[position], by_id, taken_over),
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


def _identities_older_than_their_row(
    found: Sequence[PlanRevisionRecord],
    documents: Sequence[PlanDocument],
    held: Sequence[WeekAdjustmentRecord],
) -> frozenset[UUID]:
    """The held concessions whose identifier a revision named before the row's own instant.

    That is what a replacement leaves behind, and only a replacement leaves it: the write keeps the
    replaced row's identity and takes everything else from the candidate, so the row ends up older
    than the write that last set its figures. An inserted row cannot, because its identifier is
    minted for the approval that appends the revision naming it.

    Read over the revisions the page holds, which is one more than it shows. A replacement whose
    first approval is older than that is not visible here and its concession reads as revoked, which
    is the answer the count gave before it was split.
    """
    return frozenset(
        row.id
        for row in held
        if any(
            record.created_at < row.created_at and row.id in document.adjustments
            for record, document in zip(found, documents, strict=True)
        )
    )


def _unnamed(
    record: PlanRevisionRecord,
    document: PlanDocument,
    by_id: Mapping[UUID, WeekAdjustmentRecord],
    taken_over: frozenset[UUID],
) -> UnnamedConcessions:
    """How many concessions this revision cannot name, and what the week did to each of them.

    One approval stamps one instant on the revision it appends and on the concession row it writes,
    so the row bearing this revision's instant is the one this revision's own approval wrote. A row
    that is also older than that write was replaced rather than inserted, and the identifier its
    candidate carried is what this document names and nothing holds.

    At most one identifier per revision goes that way, because an approval writes at most one
    concession. Every other missing identifier was a stored row, and only a revocation removes one.

    The replacement is counted against a missing identifier rather than on its own, so the two
    counts sum to how many are missing whatever the rows say.
    """
    missing = sum(1 for one in document.adjustments if one not in by_id)
    replaced = (
        1
        if missing
        and any(
            row.id in taken_over and row.created_at == record.created_at for row in by_id.values()
        )
        else 0
    )
    return UnnamedConcessions(revoked=missing - replaced, replaced=replaced)
