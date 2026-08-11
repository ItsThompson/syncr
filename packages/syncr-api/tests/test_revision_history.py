"""One page of a week's revision history: what each row says auto-applied, and what it was conceded.

The page is composed rather than mapped, and the two composed answers are the ones ``US-PLAN-07``
asks for beyond the columns.

**What auto-applied is a difference between two revisions.** So it is asserted over pairs, including
the pair a bounded page cannot see: the oldest row of a complete page has no predecessor and the
oldest row of a truncated one does, because the read asks for one more than it shows.

**A concession is named on the revision that carries it**, read from the document's own list of
identifiers, and one the week no longer holds under that identifier is COUNTED rather than dropped,
because a plan reported as solved under fewer concessions than it was is the failure the whole
feature exists against. The count says WHICH of the two things the week did to it, because a revoked
concession applies to nothing and a replaced one is still in force under another name.

Pure, from literals, because the composition is. The route that answers with it is driven in
``test_week_routes_integration.py`` and the approval that fills it in
``test_week_approval_integration.py``. The mapping onto the wire is asserted here too, because the
two counts are two integers of the same type and nothing else would notice them exchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from syncr_api.plans.history import revision_page
from syncr_api.plans.records import PlanRevisionRecord, WeekAdjustmentRecord
from syncr_api.plans.schemas import WeekRevisionResponse
from syncr_api.plans.stored_documents import plan_document, stored_document
from syncr_domain.identity import BindingRef
from syncr_domain.plan import AdjustmentKind
from tests.plan_documents import WEEK, a_block_holding, a_document, between

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from syncr_domain.plan import Block, PlanDocument

TENANT = uuid4()
AT = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)
LATER = datetime(2026, 2, 9, 14, 0, tzinfo=UTC)
# A third instant, for the week whose one concession is replaced twice.
LATEST = datetime(2026, 2, 9, 18, 0, tzinfo=UTC)

GYM = BindingRef.for_habit(uuid4(), index=0)
LEETCODE = BindingRef.for_task(uuid4())

# One Area's floor, so two concessions of one kind can name the same target and replace each other.
TARGET = uuid4()

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
    approval: dict[str, Any] = {
        "status": "approved",
        "reason": "user_approved",
        "approved_at": LATER,
        "created_at": LATER,
    }
    return a_revision(document, **(approval | overrides))


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


def unnamed_by(document: PlanDocument, held: Sequence[WeekAdjustmentRecord]) -> int:
    """How many concessions this document names that ``held`` does not hold, derived not restated.

    This is the single figure the history used to answer with, computed here from the corpus so the
    split can be asserted to sum to it rather than to a number a test wrote down.
    """
    holds = {one.id for one in held}
    return sum(1 for one in document.adjustments if one not in holds)


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
        assert (named.unnamed.revoked, named.unnamed.replaced) == (0, 0)

    def test_a_revision_solved_under_nothing_names_nothing_even_when_the_week_holds_one(
        self,
    ) -> None:
        # A concession approved after this revision was produced did not contribute to it, so the
        # week holding one is not a reason to name it here.
        held = a_concession()
        earlier = a_revision(a_week(a_block_holding(GYM, between(9, 10))))

        page = revision_page([earlier], held=(held,), page=PAGE)

        assert page.revisions[0].adjustments == ()
        assert (page.revisions[0].unnamed.revoked, page.revisions[0].unnamed.replaced) == (0, 0)

    def test_a_concession_the_week_revoked_is_counted_as_revoked(self) -> None:
        # A revocation deletes the row, so the document names one that is not there and nothing
        # holds that concession under any name. The only honest answer is a count: a plan reported
        # as solved under fewer concessions than it was is the silence this feature exists against.
        gone = uuid4()
        still_held = a_concession()
        approved = an_approved(
            a_week(a_block_holding(GYM, between(9, 10)), adjustments=(gone, still_held.id))
        )

        page = revision_page([approved], held=(still_held,), page=PAGE)

        assert [one.id for one in page.revisions[0].adjustments] == [still_held.id]
        assert (page.revisions[0].unnamed.revoked, page.revisions[0].unnamed.replaced) == (1, 0)

    def test_a_concession_of_another_week_reaches_no_revision_of_this_one(self) -> None:
        # The read is per week already, and this states that the pairing is by identifier rather
        # than by "every concession the reader was handed".
        elsewhere = a_concession()
        approved = an_approved(a_week(a_block_holding(GYM, between(9, 10))))

        page = revision_page([approved], held=(elsewhere,), page=PAGE)

        assert page.revisions[0].adjustments == ()


class TestWhichOfTheTwoThingsTheWeekDidToIt:
    """The count that used to stand for both causes, and what separates them.

    A replacement keeps the replaced row's identifier and takes everything else from the candidate,
    so it leaves a row whose identity an earlier revision already named and whose instant is the
    replacing approval's. That is the only way such a row exists, and it is what tells a replacement
    from a revocation, which leaves no row at all.
    """

    def test_a_concession_a_later_approval_replaced_is_counted_as_replaced(self) -> None:
        granted, replacing, taken_over = _a_replaced_concession()

        page = revision_page([replacing, granted], held=(taken_over,), page=PAGE)

        replaced, first = page.revisions
        # The row the week holds is the FIRST approval's, carrying the second's figures, so the
        # first revision names it and the second cannot.
        assert [one.id for one in first.adjustments] == [taken_over.id]
        assert (first.unnamed.revoked, first.unnamed.replaced) == (0, 0)
        assert (replaced.unnamed.revoked, replaced.unnamed.replaced) == (0, 1)

    def test_the_row_this_revision_inserted_makes_no_other_absence_a_replacement(self) -> None:
        """The case that separates "a row bears this instant" from "a row older than this write".

        This approval INSERTED its own concession, and a different one the same plan was solved
        under has since been revoked. A row does bear this revision's instant, so a reading that
        stopped there would report the revocation as a replacement.
        """
        gone = uuid4()
        inserted = a_concession(created_at=LATER)
        approved = an_approved(
            a_week(a_block_holding(GYM, between(9, 10)), adjustments=(gone, inserted.id))
        )

        page = revision_page([approved], held=(inserted,), page=PAGE)

        assert (page.revisions[0].unnamed.revoked, page.revisions[0].unnamed.replaced) == (1, 0)

    def test_the_two_counts_sum_to_the_concessions_the_week_cannot_name(self) -> None:
        """Asserted over a week holding both causes, against the figure the history used to give.

        The expected total is derived from the corpus rather than written down, so this cannot pass
        by agreeing with a number that is itself wrong.
        """
        revoked = uuid4()
        granted, replacing, taken_over = _a_replaced_concession(also_naming=(revoked,))
        held = (taken_over,)

        page = revision_page([replacing, granted], held=held, page=PAGE)

        assert (page.revisions[0].unnamed.revoked, page.revisions[0].unnamed.replaced) == (1, 1)
        assert (page.revisions[1].unnamed.revoked, page.revisions[1].unnamed.replaced) == (1, 0)
        for revision, document in zip(page.revisions, (replacing, granted), strict=True):
            counted = revision.unnamed.revoked + revision.unnamed.replaced
            assert counted == unnamed_by(plan_document(document.document), held)

    def test_a_replacement_the_page_cannot_see_the_grant_of_reads_as_revoked(self) -> None:
        """The bound on the discrimination, pinned rather than left to be discovered.

        The identity is read off the revisions the page holds. A replacement whose first approval is
        older than that window is invisible here, and the concession falls back to the answer the
        single count gave: one this revision cannot name.
        """
        granted, replacing, taken_over = _a_replaced_concession()
        between_them = a_revision(a_week(a_block_holding(LEETCODE, between(14, 15))), created_at=AT)

        whole = revision_page([replacing, between_them, granted], held=(taken_over,), page=2)
        without_the_grant = revision_page([replacing, between_them], held=(taken_over,), page=1)

        assert (whole.revisions[0].unnamed.revoked, whole.revisions[0].unnamed.replaced) == (0, 1)
        assert without_the_grant.truncated is True
        first = without_the_grant.revisions[0]
        assert (first.unnamed.revoked, first.unnamed.replaced) == (1, 0)

    def test_a_second_replacement_of_one_target_reports_the_earlier_one_as_revoked(self) -> None:
        """The second bound on the discrimination, pinned in the same shape as the page bound.

        A row bears the instant of the write that LAST set its figures, and only one revision can
        bear it, so exactly one revision is ever credited with a replacement of one row. Replace the
        same kind and target twice and the earlier replacement reports its concession as revoked,
        which is the pre-split answer and the one the count exists to stop giving. Every revision is
        on the page here, so this is not the window bound the test above pins.

        The sum survives: the earlier revision is missing one identifier and reports one.

        Neither label is exactly right for that revision. Its figures are not in force any more, so
        `replaced` would also be false, and a third case is what the state really is. `revoked` is
        the worse of the two available answers, because it tells a reader to act and the enumerator
        will not re-offer a kind and target the week already holds.
        """
        first = uuid4()
        granted = an_approved(
            a_week(a_block_holding(GYM, between(9, 10)), adjustments=(first,)),
            created_at=AT,
            approved_at=AT,
        )
        replacing = an_approved(
            a_week(a_block_holding(GYM, between(9, 10)), adjustments=(first, uuid4())),
            created_at=LATER,
            approved_at=LATER,
        )
        replacing_again = an_approved(
            a_week(a_block_holding(GYM, between(9, 10)), adjustments=(first, uuid4())),
            created_at=LATEST,
            approved_at=LATEST,
        )
        # The row still carries the FIRST identifier. After one replacement it bears that write's
        # instant; after the second it bears the second's, which is the whole of the difference.
        after_one = a_concession(id=first, target_id=TARGET, created_at=LATER)
        after_two = a_concession(id=first, target_id=TARGET, created_at=LATEST)

        once = revision_page([replacing, granted], held=(after_one,), page=3)
        twice = revision_page([replacing_again, replacing, granted], held=(after_two,), page=3)

        assert [(one.unnamed.revoked, one.unnamed.replaced) for one in once.revisions] == [
            (0, 1),
            (0, 0),
        ]
        assert [(one.unnamed.revoked, one.unnamed.replaced) for one in twice.revisions] == [
            (0, 1),
            (1, 0),
            (0, 0),
        ]
        for revision, record in zip(
            twice.revisions, (replacing_again, replacing, granted), strict=True
        ):
            counted = revision.unnamed.revoked + revision.unnamed.replaced
            assert counted == unnamed_by(plan_document(record.document), (after_two,))

    def test_a_revision_missing_nothing_reports_no_replacement_to_go_with_it(self) -> None:
        """The totality of the pair, over a corpus the writers cannot produce.

        A row older than its own write, bearing this revision's instant, while the document names
        every concession the week holds. The attribution matches and there is no absence to explain,
        so a reading that counted the replacement on its own would answer with a pair that does not
        sum: one replacement against nothing missing, and a negative revocation to balance it.

        An approval cannot leave this state, because a document is appended naming the candidate
        the approval wrote and a replacement is exactly the case where nothing holds that
        identifier. The composition is pure, so the state is still reachable as an argument, and
        what it asserts is the sentence the pair carries: the two counts sum to the identifiers the
        week cannot name, whatever the rows say.
        """
        first = uuid4()
        granted = an_approved(
            a_week(a_block_holding(GYM, between(9, 10)), adjustments=(first,)),
            created_at=AT,
            approved_at=AT,
        )
        naming_only_what_is_held = an_approved(
            a_week(a_block_holding(GYM, between(9, 10)), adjustments=(first,))
        )
        taken_over = a_concession(id=first, target_id=TARGET, created_at=LATER)

        page = revision_page([naming_only_what_is_held, granted], held=(taken_over,), page=PAGE)

        unnamed = page.revisions[0].unnamed
        assert (unnamed.revoked, unnamed.replaced) == (0, 0)
        assert unnamed.revoked + unnamed.replaced == unnamed_by(
            plan_document(naming_only_what_is_held.document), (taken_over,)
        )


class TestWhatTheHistoryPutsOnTheWire:
    def test_each_count_reaches_the_wire_under_its_own_name(self) -> None:
        """Two integers of one type, so nothing but this would notice them exchanged.

        The discriminating assertion is the `replacedAdjustments` list: it reads 1 then 0, so a swap
        makes it read 1 then 1. The revoked list is 1 on both revisions and cannot tell the two
        mappings apart, and it is asserted because the swap has to be wrong about both.
        """
        revoked = uuid4()
        granted, replacing, taken_over = _a_replaced_concession(also_naming=(revoked,))

        page = revision_page([replacing, granted], held=(taken_over,), page=PAGE)
        rendered = [
            WeekRevisionResponse.of(one).model_dump(by_alias=True) for one in page.revisions
        ]

        assert [one["replacedAdjustments"] for one in rendered] == [1, 0]
        assert [one["revokedAdjustments"] for one in rendered] == [1, 1]


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


def _a_replaced_concession(
    *, also_naming: tuple[UUID, ...] = ()
) -> tuple[PlanRevisionRecord, PlanRevisionRecord, WeekAdjustmentRecord]:
    """Two approvals of one kind and target, and the row the second left behind.

    The first approval's row takes the first candidate's identifier. The second approval's upsert
    finds it on the unique index, so the row keeps that identifier and takes the second candidate's
    instant and figures: what the second revision names, nothing holds. Its document names both,
    because the solve behind it read the stored row and folded its own candidate on top.

    ``also_naming`` are identifiers both documents were solved under that the week has since
    revoked, which is how one week comes to hold both causes at once.
    """
    first = uuid4()
    second = uuid4()
    granted = an_approved(
        a_week(a_block_holding(GYM, between(9, 10)), adjustments=(*also_naming, first)),
        reason="tradeoff_approved",
        created_at=AT,
        approved_at=AT,
    )
    replacing = an_approved(
        a_week(a_block_holding(GYM, between(9, 10)), adjustments=(*also_naming, first, second)),
        reason="tradeoff_approved",
        created_at=LATER,
        approved_at=LATER,
    )
    taken_over = a_concession(id=first, target_id=TARGET, created_at=LATER)
    return granted, replacing, taken_over
