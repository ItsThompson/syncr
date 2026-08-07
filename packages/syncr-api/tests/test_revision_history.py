"""One page of a week's revision history: what each row says auto-applied, and what it was conceded.

The page is composed rather than mapped, and the two composed answers are the ones ``US-PLAN-07``
asks for beyond the columns.

**What auto-applied is a difference between two revisions.** So it is asserted over pairs, including
the pair a bounded page cannot see: the oldest row of a complete page has no predecessor and the
oldest row of a truncated one does, because the read asks for one more than it shows.

**A concession is named on the revision that carries it**, read from the document's own list of
identifiers, and one the week no longer holds under that identifier is COUNTED rather than dropped,
because a plan reported as solved under fewer concessions than it was is the failure the whole
feature exists against.

Pure, from literals, because the composition is. The route that answers with it is driven in
``test_week_routes_integration.py`` and the approval that fills it in
``test_week_approval_integration.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from syncr_api.plans.history import revision_page
from syncr_api.plans.records import PlanRevisionRecord, WeekAdjustmentRecord
from syncr_api.plans.stored_documents import stored_document
from syncr_domain.identity import BindingRef
from syncr_domain.plan import AdjustmentKind
from tests.plan_documents import WEEK, a_block_holding, a_document, between

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_domain.plan import Block, PlanDocument

TENANT = uuid4()
AT = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)
LATER = datetime(2026, 2, 9, 14, 0, tzinfo=UTC)

GYM = BindingRef.for_habit(uuid4(), index=0)
LEETCODE = BindingRef.for_task(uuid4())

PAGE = 2


def a_week(*blocks: Block, **overrides: Any) -> PlanDocument:
    return a_document(week=WEEK, blocks=blocks, **overrides)


def a_revision(document: PlanDocument, **overrides: Any) -> PlanRevisionRecord:
    fields: dict[str, Any] = {
        "id": uuid4(),
        "tenant_id": TENANT,
        "iso_week": WEEK,
        "status": "applied",
        "reason": "auto_applied_fill",
        "document": stored_document(document),
        "objective_breakdown": {},
        "weight_set_version": 1,
        "input_version": 3,
        "supersedes_id": None,
        "created_at": AT,
        "approved_at": None,
    }
    return PlanRevisionRecord(**(fields | overrides))


def an_approved(document: PlanDocument, **overrides: Any) -> PlanRevisionRecord:
    return a_revision(
        document,
        status="approved",
        reason="user_approved",
        approved_at=LATER,
        created_at=LATER,
        **overrides,
    )


def a_concession(**overrides: Any) -> WeekAdjustmentRecord:
    fields: dict[str, Any] = {
        "id": uuid4(),
        "tenant_id": TENANT,
        "iso_week": WEEK,
        "kind": AdjustmentKind.BREACH_FLOOR.value,
        "target_id": uuid4(),
        "reductions": {},
        "delta_minutes": 80,
        "created_at": AT,
        "created_by_operation_id": uuid4(),
    }
    return WeekAdjustmentRecord(**(fields | overrides))


def titles_of(page: Any) -> list[list[str]]:
    return [list(one.auto_applied) for one in page.revisions]


class TestWhatARevisionSaysItAutoApplied:
    def test_an_applied_revision_names_the_block_it_added_without_asking(self) -> None:
        # The authority rule says an `applied` revision is a candidate that filled empty space and
        # did nothing else, so the block its predecessor does not hold IS what applied unasked. The
        # reason column can only say WHICH RULE let it through.
        first = a_revision(a_week(a_block_holding(GYM, between(9, 10))))
        second = a_revision(
            a_week(
                a_block_holding(GYM, between(9, 10)), a_block_holding(LEETCODE, between(14, 15))
            ),
            created_at=LATER,
        )

        page = revision_page([second, first], held=(), page=PAGE)

        assert titles_of(page) == [["task · something"], []]

    def test_an_approved_revision_names_nothing_it_auto_applied(self) -> None:
        # Its changes are the ones the user assented to, which is what the diff they were shown
        # named. Reporting them here would say the product had applied them on its own.
        first = a_revision(a_week(a_block_holding(GYM, between(9, 10))))
        approved = an_approved(
            a_week(
                a_block_holding(GYM, between(17, 18)), a_block_holding(LEETCODE, between(14, 15))
            )
        )

        page = revision_page([approved, first], held=(), page=PAGE)

        assert titles_of(page) == [[], []]

    def test_the_first_plan_a_week_ever_had_names_nothing(self) -> None:
        # It added everything and asked about nothing, so listing a whole week as a change would
        # say nothing a reader can use. The reason column says the maintainer produced it.
        only = a_revision(a_week(a_block_holding(GYM, between(9, 10))), reason="materialized")

        page = revision_page([only], held=(), page=PAGE)

        assert titles_of(page) == [[]]
        assert page.truncated is False

    def test_the_oldest_row_of_a_truncated_page_reads_the_predecessor_it_cannot_show(self) -> None:
        """The extra row a bounded read asks for is used twice, and this is the second use.

        Without it the oldest row on every page would report the whole week as auto-applied, which
        is the answer a reader gets exactly when the history is long enough to be worth paging.
        """
        oldest = a_revision(a_week(a_block_holding(GYM, between(9, 10))))
        middle = a_revision(
            a_week(
                a_block_holding(GYM, between(9, 10)), a_block_holding(LEETCODE, between(14, 15))
            ),
            created_at=LATER,
        )
        newest = an_approved(a_week(a_block_holding(GYM, between(9, 10))))

        page = revision_page([newest, middle, oldest], held=(), page=PAGE)

        assert page.truncated is True
        assert [one.record.id for one in page.revisions] == [newest.id, middle.id]
        assert titles_of(page) == [[], ["task · something"]]


class TestTheConcessionsAPlanWasSolvedUnder:
    def test_a_concession_is_named_on_the_revision_whose_plan_was_solved_under_it(self) -> None:
        held = a_concession()
        approved = an_approved(a_week(a_block_holding(GYM, between(9, 10)), adjustments=(held.id,)))

        page = revision_page([approved], held=(held,), page=PAGE)

        named = page.revisions[0]
        assert [one.id for one in named.adjustments] == [held.id]
        assert named.unnamed_adjustments == 0

    def test_a_revision_solved_under_nothing_names_nothing_even_when_the_week_holds_one(
        self,
    ) -> None:
        # A concession approved after this revision was produced did not contribute to it, so the
        # week holding one is not a reason to name it here.
        held = a_concession()
        earlier = a_revision(a_week(a_block_holding(GYM, between(9, 10))))

        page = revision_page([earlier], held=(held,), page=PAGE)

        assert page.revisions[0].adjustments == ()
        assert page.revisions[0].unnamed_adjustments == 0

    def test_a_concession_the_week_no_longer_holds_is_counted_rather_than_dropped(self) -> None:
        # A revocation deletes the row and a later concession of the same kind and target replaces
        # it under the REPLACED row's identifier, so both leave the document naming a row that is
        # not there. The only honest answer is a count: a plan reported as solved under fewer
        # concessions than it was is the silence this whole feature exists against.
        gone = uuid4()
        still_held = a_concession()
        approved = an_approved(
            a_week(a_block_holding(GYM, between(9, 10)), adjustments=(gone, still_held.id))
        )

        page = revision_page([approved], held=(still_held,), page=PAGE)

        assert [one.id for one in page.revisions[0].adjustments] == [still_held.id]
        assert page.revisions[0].unnamed_adjustments == 1

    def test_a_concession_of_another_week_reaches_no_revision_of_this_one(self) -> None:
        # The read is per week already, and this states that the pairing is by identifier rather
        # than by "every concession the reader was handed".
        elsewhere = a_concession()
        approved = an_approved(a_week(a_block_holding(GYM, between(9, 10))))

        page = revision_page([approved], held=(elsewhere,), page=PAGE)

        assert page.revisions[0].adjustments == ()


class TestThePageIsBounded:
    def test_a_page_exactly_as_long_as_its_bound_is_not_truncated(self) -> None:
        # The reason the read asks for one more than it shows: without the extra row these two
        # cases are indistinguishable.
        rows = _two_revisions()

        page = revision_page(rows, held=(), page=PAGE)

        assert len(page.revisions) == PAGE
        assert page.truncated is False

    def test_a_page_holding_more_than_its_bound_says_so_and_shows_the_bound(self) -> None:
        rows = [*_two_revisions(), a_revision(a_week())]

        page = revision_page(rows, held=(), page=PAGE)

        assert len(page.revisions) == PAGE
        assert page.truncated is True


def _two_revisions() -> Sequence[PlanRevisionRecord]:
    return [
        an_approved(a_week(a_block_holding(GYM, between(9, 10)))),
        a_revision(a_week(a_block_holding(GYM, between(9, 10)))),
    ]
