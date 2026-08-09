"""The weekly session's pure rules: what a run of weeks is, and what each raise says.

Three rules and one composition, asserted over hand-built values so every boundary is reachable
without a plan document in a database. The route suite proves the wire shape and that the read
writes nothing; this proves the counting.

The two counts are deliberately different and the tests say so: a chronic skip is a run of
CONSECUTIVE weeks, and a repeated collision is a count of DISTINCT weeks. Both stories are quoted at
the case that separates them.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from syncr_api.habits.records import HabitRecord
from syncr_api.plans.records import BlockOutcomeRecord, ConflictRecord
from syncr_api.reviews.collisions import repeated_collision_items, repeated_collisions
from syncr_api.reviews.coverage import ReviewedDay
from syncr_api.reviews.history import ReviewedWeek
from syncr_api.reviews.naming import a_kind, block_titles
from syncr_api.reviews.raised import RaisedKind, floor_items, habit_debt_items, overdue_items
from syncr_api.reviews.skips import chronic_skip_items, chronic_skips
from syncr_api.reviews.statements import period_statement
from syncr_api.tasks.records import TaskRecord
from syncr_domain.debt import DebtReading
from syncr_domain.feasibility import Provenance, Shortfall, ShortfallKind, Verdict
from syncr_domain.habits import BindingSource, CadenceKind, MissPolicy
from syncr_domain.identity import BindingKind, BindingRef
from syncr_domain.intervals import Interval, IntervalSet
from syncr_domain.outcomes import OutcomeState
from syncr_domain.reasons import Bound, ReasonRecord
from syncr_domain.tasks import Priority, TaskStatus
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_domain.plan import Block
    from syncr_domain.zones import Date

A_REASON = ReasonRecord((Bound(BindingSource.ROTATION, "Gym · rotation"),))
CONFIRMED_AT = datetime(2026, 3, 1, 21, 0, tzinfo=UTC)
NOW = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)

# One habit and one task, held as identities so a run over six weeks names one thing.
GYM = uuid4()
LEETCODE = uuid4()

# Six consecutive weeks, which is exactly what `US-REV-02` raises on.
RUN = [IsoWeek(2026, number) for number in (2, 3, 4, 5, 6, 7)]

# The one block every conflict below names, as the window's own blocks would answer for it. Keyed on
# the content, which is what a binding's occurrence key drops out of.
LEETCODE_TITLE = {BindingRef.for_task(LEETCODE).content_key: "Leetcode"}


def an_instant(on: Date, hour: int) -> datetime:
    return datetime.combine(on, time(hour), tzinfo=UTC)


def a_block(*, iso_week: IsoWeek, entity_id: object = GYM, index: int = 0, title: str) -> Block:
    from syncr_domain.plan import Block

    monday = iso_week.monday()
    return Block(
        iso_week=iso_week,
        interval=Interval(an_instant(monday, 9), an_instant(monday, 10)),
        binding=BindingRef.for_habit(entity_id, index=index),  # type: ignore[arg-type]
        title=title,
        reason=A_REASON,
        area_id=uuid4(),
    )


def an_outcome(block: Block, state: OutcomeState, *, confirmed: bool = True) -> BlockOutcomeRecord:
    return BlockOutcomeRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        block_id=block.id,
        binding=block.binding,
        revision_id=uuid4(),
        state=state,
        actual_minutes=None,
        actual_interval=None,
        occurred_at=block.interval.start,
        confirmed_at=CONFIRMED_AT if confirmed else None,
    )


def a_week(
    iso_week: IsoWeek,
    *,
    blocks: Sequence[Block] = (),
    states: Sequence[OutcomeState] = (),
    confirmed: bool = True,
) -> ReviewedWeek:
    """One reviewed week holding ``blocks``, each with the outcome at the same position."""
    monday = iso_week.monday()
    span = Interval(an_instant(monday, 0), an_instant(iso_week.following().monday(), 0))
    outcomes = {
        str(block.id): an_outcome(block, state, confirmed=confirmed)
        for block, state in zip(blocks, states, strict=True)
    }
    day = ReviewedDay(
        on=monday,
        span=Interval(an_instant(monday, 0), an_instant(monday + timedelta(days=1), 0)),
        blocks=tuple(blocks),
        confirmed_at=CONFIRMED_AT if confirmed else None,
        is_off_plan=False,
    )
    return ReviewedWeek(
        iso_week=iso_week,
        span=span,
        discretionary_minutes=10080,
        days=(day,),
        off_plan=IntervalSet(),
        covered={},
        outcomes=outcomes,
    )


def skipped_run(weeks: Sequence[IsoWeek], *, title: str = "Gym") -> list[ReviewedWeek]:
    """One habit proposed and confirmed-skipped in each of ``weeks``, keyed per week."""
    built = []
    for offset, week in enumerate(weeks):
        block = a_block(iso_week=week, index=offset, title=title)
        built.append(a_week(week, blocks=[block], states=[OutcomeState.SKIPPED]))
    return built


def a_task(*, title: str, deadline: datetime | None) -> TaskRecord:
    """One open task, with only the fields the overdue raise reads set to anything meaningful."""
    return TaskRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        area_id=uuid4(),
        project_id=None,
        title=title,
        estimate_minutes=60,
        deadline=deadline,
        priority=Priority.NORMAL,
        min_chunk_minutes=30,
        splittable=True,
        status=TaskStatus.OPEN,
        recorded_minutes=0,
        completed_at=None,
        created_at=CONFIRMED_AT,
    )


def a_habit(*, title: str) -> HabitRecord:
    """One habit, as the raise names it."""
    return HabitRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        area_id=uuid4(),
        title=title,
        cadence_kind=CadenceKind.TIMES_PER_WEEK,
        cadence_times_per_week=3,
        cadence_approx_days=None,
        duration_min_minutes=45,
        duration_max_minutes=60,
        miss_policy=MissPolicy.DEBT,
        binding_source=BindingSource.FIXED,
        variants=(),
        debt_cap_periods=2,
        created_at=CONFIRMED_AT,
    )


def a_debt_reading(*, raised_in_weekly_session: bool) -> DebtReading:
    """A reading whose only interesting field is the one the raise is conditioned on.

    Built rather than derived, because what is under test here is which habits become items: whether
    a habit is raised at all is ``syncr_domain.debt``'s own rule and has its own suite.
    """
    return DebtReading(
        misses=2,
        outstanding=2,
        cap=6,
        forgiven_at_cap=1 if raised_in_weekly_session else 0,
        raised_in_weekly_session=raised_in_weekly_session,
        statement="Two sessions behind, capped at six.",
    )


class TestAChronicSkipIsSixConsecutiveWeeks:
    def test_six_weeks_of_confirmed_skips_are_raised(self) -> None:
        found = chronic_skips(skipped_run(RUN), consecutive_weeks=6)

        assert len(found) == 1
        assert found[0].consecutive_weeks == 6
        assert found[0].title == "Gym"

    def test_five_weeks_are_below_the_threshold(self) -> None:
        assert chronic_skips(skipped_run(RUN[:5]), consecutive_weeks=6) == []

    def test_a_gap_in_the_middle_breaks_the_run(self) -> None:
        # A week that did not propose the item holds no skip of it, so the run restarts. The story's
        # words are "proposed and skipped": an item the plan stopped offering is not one declined.
        #
        # SEVEN weeks with a gap in the fourth, so SIX of them hold a skip and the longest run is
        # three. A rule that counted distinct weeks would raise this, which is what separates the
        # two readings: the threshold alone cannot tell them apart.
        seven = [IsoWeek(2026, number) for number in (2, 3, 4, 5, 6, 7, 8)]
        broken = [
            *skipped_run(seven[:3]),
            a_week(seven[3]),
            *skipped_run(seven[4:]),
        ]
        skipped = sum(1 for week in broken if week.outcomes)

        assert skipped == 6, "six weeks hold a skip, so a count of distinct weeks would raise"
        assert chronic_skips(broken, consecutive_weeks=6) == []

    def test_the_occurrence_key_differing_per_week_does_not_break_the_group(self) -> None:
        # The key is scoped to its own week, so two occurrences of one habit in two weeks never
        # share one. Grouping on the whole binding would find a run of one every time.
        weeks = skipped_run(RUN)
        keys = {
            str(block.binding.occurrence_key) for week in weeks for block in week.days[0].blocks
        }

        assert len(keys) == 6
        assert chronic_skips(weeks, consecutive_weeks=6)[0].consecutive_weeks == 6

    def test_two_skips_of_one_item_in_one_week_are_one_week_of_evidence(self) -> None:
        twice = a_block(iso_week=RUN[0], index=9, title="Gym")
        weeks = skipped_run(RUN[:5])
        weeks[0] = a_week(
            RUN[0],
            blocks=[weeks[0].days[0].blocks[0], twice],
            states=[OutcomeState.SKIPPED, OutcomeState.SKIPPED],
        )

        assert chronic_skips(weeks, consecutive_weeks=6) == []

    def test_an_unconfirmed_skip_is_not_a_skip(self) -> None:
        # The narrowing `syncr_domain.debt` takes, for the same reason: an unconfirmed block is
        # presumed, and presuming a week and reporting it as behaviour is how a review escalates
        # something the user actually did.
        weeks = [
            a_week(
                week,
                blocks=[a_block(iso_week=week, index=offset, title="Gym")],
                states=[OutcomeState.SKIPPED],
                confirmed=False,
            )
            for offset, week in enumerate(RUN)
        ]

        assert chronic_skips(weeks, consecutive_weeks=6) == []

    def test_a_completed_occurrence_is_not_a_skip(self) -> None:
        weeks = [
            a_week(
                week,
                blocks=[a_block(iso_week=week, index=offset, title="Gym")],
                states=[OutcomeState.COMPLETED],
            )
            for offset, week in enumerate(RUN)
        ]

        assert chronic_skips(weeks, consecutive_weeks=6) == []

    def test_a_run_across_a_year_boundary_is_still_a_run(self) -> None:
        # 2026-W53 is followed by 2027-W01, so the week number alone does not decide the answer.
        crossing = [
            IsoWeek(2026, 50),
            IsoWeek(2026, 51),
            IsoWeek(2026, 52),
            IsoWeek(2026, 53),
            IsoWeek(2027, 1),
            IsoWeek(2027, 2),
        ]

        assert chronic_skips(skipped_run(crossing), consecutive_weeks=6)[0].consecutive_weeks == 6

    def test_the_raise_states_the_item_and_the_count_and_offers_nothing(self) -> None:
        (item,) = chronic_skip_items(chronic_skips(skipped_run(RUN), consecutive_weeks=6))

        assert item.kind is RaisedKind.CHRONIC_SKIP
        assert item.title == "Gym"
        assert "6 weeks" in item.statement
        assert f"Most recently {RUN[-1]}." in item.statement
        assert "has not changed its priority" in item.statement


class TestTheWordForContentTheWindowCannotName:
    """``a_kind`` is the ONE fallback both naming surfaces of this payload take.

    It reads ``Origin``, which is the vocabulary the grid and the ledger render, rather than
    ``BindingKind``, which is the wire's. Three of the seven kinds are spelled differently between
    the two, and all three are reachable here: ``plans.overlaps`` skips only ``Origin.ANCHOR`` when
    it collects the blocks a commitment can land on, so a prep or a transit block can be the one a
    repeated collision names.
    """

    def test_every_binding_kind_takes_the_readers_word_and_the_right_article(self) -> None:
        assert {kind: a_kind(kind) for kind in BindingKind} == {
            BindingKind.ROUTINE: "a frame",
            BindingKind.TEMPLATE_ENTRY: "a template entry",
            BindingKind.HABIT: "a habit",
            BindingKind.TASK: "a task",
            BindingKind.ANCHOR: "an anchor",
            BindingKind.ANCHOR_PREP: "a prep",
            BindingKind.ANCHOR_TRANSIT: "a transit",
        }

    def test_it_is_total_over_the_vocabulary_rather_than_a_list_of_seven(self) -> None:
        # Derived, so a kind added to either enum arrives with its own word rather than with a
        # KeyError or a wrong article.
        for kind in BindingKind:
            said = a_kind(kind)
            assert said.startswith(("a ", "an ")), kind
            assert "_" not in said, kind

    def test_a_prep_block_a_commitment_landed_on_is_named_as_a_prep(self) -> None:
        # The shape the wire spelling would have rendered as "a anchor prep".
        prep = BindingRef.for_anchor_prep(uuid4())
        rows = [a_conflict(iso_week=week, binding=prep) for week in RUN[:3]]

        (item,) = repeated_collision_items(repeated_collisions(rows, at_least_weeks=3), titles={})

        assert item.title == "Standup over a prep"


def a_conflict(
    *,
    iso_week: IsoWeek,
    series_uid: str | None = "standup-series",
    title: str | None = "Standup",
    binding: BindingRef | None = None,
) -> ConflictRecord:
    """One retained conflict, naming a commitment's series and a block's binding."""
    held = binding if binding is not None else BindingRef.for_task(LEETCODE)
    monday = iso_week.monday()
    return ConflictRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        iso_week=iso_week,
        anchor_id=uuid4(),
        block_id=f"{iso_week}-{uuid4()}",
        binding=held,
        series_uid=series_uid,
        commitment_title=title,
        overlap=Interval(an_instant(monday, 9), an_instant(monday, 10)),
        detected_at=CONFIRMED_AT,
        resolved_at=CONFIRMED_AT,
        resolution="moved",
    )


class TestARepeatedCollisionIsThreeOrMoreWeeks:
    def test_three_weeks_of_one_pair_are_raised(self) -> None:
        rows = [a_conflict(iso_week=week) for week in RUN[:3]]

        (found,) = repeated_collisions(rows, at_least_weeks=3)

        assert found.week_count == 3
        assert found.commitment == "Standup"

    def test_two_weeks_are_below_the_threshold(self) -> None:
        assert (
            repeated_collisions([a_conflict(iso_week=week) for week in RUN[:2]], at_least_weeks=3)
            == []
        )

    def test_the_weeks_need_not_be_consecutive(self) -> None:
        # The story's words are "three or more weeks", which is weaker than the consecutive run a
        # chronic skip is stated over. A collision resolved one week and met again two weeks later
        # is the same pattern.
        scattered = [a_conflict(iso_week=IsoWeek(2026, number)) for number in (2, 5, 9)]

        assert repeated_collisions(scattered, at_least_weeks=3)[0].week_count == 3

    def test_two_rows_in_one_week_count_once(self) -> None:
        # Detection runs at ingest on every sync and again on every solve's commit path, so rows
        # are not a measure of anything the user experienced.
        rows = [a_conflict(iso_week=RUN[0]) for _ in range(4)] + [a_conflict(iso_week=RUN[1])]

        assert repeated_collisions(rows, at_least_weeks=3) == []

    def test_the_anchor_ids_are_all_different_and_the_group_still_holds(self) -> None:
        # This is the whole reason the series is denormalized: a weekly commitment publishes a
        # distinct occurrence per week, so grouping on anchor_id would find a group of one.
        rows = [a_conflict(iso_week=week) for week in RUN[:3]]

        assert len({row.anchor_id for row in rows}) == 3
        assert repeated_collisions(rows, at_least_weeks=3)[0].week_count == 3

    def test_a_commitment_with_no_series_never_contributes(self) -> None:
        # A one-off cannot recur, so a row carrying no series is not part of any pattern.
        rows = [a_conflict(iso_week=week, series_uid=None) for week in RUN[:5]]

        assert repeated_collisions(rows, at_least_weeks=3) == []

    def test_a_one_off_sharing_the_block_and_weeks_is_not_raised_beside_the_series(self) -> None:
        # The series is the only thing separating these two pairs: one block, one pair of weeks.
        # A one-off cannot recur, so the pair carrying none is skipped rather than raised as a
        # second pattern over the same block. Two seriesless rows rather than one, because one row
        # groups to a single week and no threshold above one could raise it either way.
        standup = [a_conflict(iso_week=week) for week in RUN[:2]]
        one_offs = [a_conflict(iso_week=week, series_uid=None, title="Dentist") for week in RUN[:2]]

        found = repeated_collisions([*standup, *one_offs], at_least_weeks=2)

        assert [one.commitment for one in found] == ["Standup"]
        assert found[0].weeks == (RUN[0], RUN[1])

    def test_two_different_series_over_one_block_are_two_groups(self) -> None:
        standup = [a_conflict(iso_week=week) for week in RUN[:3]]
        lecture = [
            a_conflict(iso_week=week, series_uid="lecture-series", title="Lecture")
            for week in RUN[:3]
        ]

        found = repeated_collisions([*standup, *lecture], at_least_weeks=3)

        assert {one.commitment for one in found} == {"Standup", "Lecture"}

    def test_one_series_over_two_blocks_is_two_groups(self) -> None:
        leetcode = [a_conflict(iso_week=week) for week in RUN[:3]]
        gym = [
            a_conflict(iso_week=week, binding=BindingRef.for_habit(GYM, index=0))
            for week in RUN[:3]
        ]

        assert len(repeated_collisions([*leetcode, *gym], at_least_weeks=3)) == 2

    def test_a_group_whose_commitment_was_never_named_states_the_block_alone(self) -> None:
        # What the solve commit path writes for an anchor deleted before the raise reached it. The
        # count and one name, rather than an invented second one.
        rows = [a_conflict(iso_week=week, title=None) for week in RUN[:3]]

        (item,) = repeated_collision_items(
            repeated_collisions(rows, at_least_weeks=3), titles=LEETCODE_TITLE
        )

        assert item.title == "Leetcode"
        assert "An imported commitment has landed on Leetcode in 3 weeks" in item.statement

    def test_the_raise_names_the_commitment_the_block_and_the_count(self) -> None:
        # `US-REV-05`'s own example is `repeated collision: Standup over Leetcode, 4 weeks`, so both
        # ends and the count are named. The block's name comes from a block, because the conflict
        # row stores a binding and no title.
        rows = [a_conflict(iso_week=week) for week in RUN[:4]]

        (item,) = repeated_collision_items(
            repeated_collisions(rows, at_least_weeks=3), titles=LEETCODE_TITLE
        )

        assert item.kind is RaisedKind.REPEATED_COLLISION
        assert item.title == "Standup over Leetcode"
        assert "Standup has landed on Leetcode in 4 weeks" in item.statement
        assert "Stated rather than acted on" in item.statement

    def test_a_block_no_reviewed_week_holds_falls_back_to_its_kind(self) -> None:
        # A pattern whose block the window has lost is still worth stating with a poor name, which
        # is the fallback the promotion candidate takes for the same reason.
        rows = [a_conflict(iso_week=week) for week in RUN[:3]]

        (item,) = repeated_collision_items(repeated_collisions(rows, at_least_weeks=3), titles={})

        assert item.title == "Standup over a task"
        assert "landed on a task in 3 weeks" in item.statement

    def test_a_pair_that_can_name_neither_end_is_not_raised_at_all(self) -> None:
        # THE FOURTH CELL of the naming matrix, and the one shape that is suppressed. A conflict
        # whose anchor had gone when the solve committed carries no commitment, and a block no week
        # of the window holds has no title: "something collided with something three times" is not
        # a pattern anybody can look into, and this raise suggests no action to make up the gap.
        rows = [a_conflict(iso_week=week, title=None) for week in RUN[:3]]

        assert repeated_collisions(rows, at_least_weeks=3), "the pattern itself must still be found"
        assert (
            repeated_collision_items(repeated_collisions(rows, at_least_weeks=3), titles={}) == []
        )

    def test_the_raise_states_the_week_the_pattern_was_last_seen_in(self) -> None:
        # A run expires with the window, but nothing else says WHERE inside it the run sits: without
        # this, three weeks that ended twelve weeks ago read like three that ended last week.
        rows = [a_conflict(iso_week=week) for week in RUN[:3]]

        (item,) = repeated_collision_items(
            repeated_collisions(rows, at_least_weeks=3), titles=LEETCODE_TITLE
        )

        assert f"Most recently {RUN[2]}." in item.statement

    def test_the_titles_are_read_from_the_blocks_of_the_window(self) -> None:
        # `block_titles` turns a window's blocks into the lookup, and the LAST title wins, so a
        # rename resolves to what the reader last saw rather than to what they saw in January.
        renamed = a_block(iso_week=RUN[0], entity_id=GYM, title="Gym")
        later = a_block(iso_week=RUN[1], entity_id=GYM, index=1, title="Gym · legs")

        titles = block_titles([renamed, later])

        assert titles[later.binding.content_key] == "Gym · legs"


class TestTheFloorAndTheOverdueRaises:
    def test_only_the_two_floor_shortfalls_are_raised_as_floors(self) -> None:
        verdict = Verdict(
            feasible=False,
            provenance=Provenance.PROBE,
            computed_at=NOW,
            input_version=1,
            discretionary_minutes=10080,
            shortfalls=(
                Shortfall(
                    kind=ShortfallKind.AREA_FLOOR_UNREACHABLE,
                    minutes=90,
                    against=("Career",),
                    honoring=("the frame",),
                ),
                Shortfall(
                    kind=ShortfallKind.DEADLINE_CAPACITY,
                    minutes=60,
                    against=("Leetcode",),
                    honoring=("the frame",),
                    deadline=NOW,
                ),
            ),
        )

        found = floor_items(verdict)

        assert [one.kind for one in found] == [RaisedKind.FLOOR_AT_RISK]
        assert found[0].title == "Career"
        assert "1h30m" in found[0].statement

    def test_a_week_with_no_verdict_raises_no_floor(self) -> None:
        assert floor_items(None) == []

    def test_only_a_task_whose_deadline_has_passed_is_overdue(self) -> None:
        past = a_task(title="Leetcode", deadline=NOW - timedelta(days=1))
        ahead = a_task(title="Essay", deadline=NOW + timedelta(days=1))
        undated = a_task(title="Read", deadline=None)

        found = overdue_items([past, ahead, undated], now=NOW)

        assert [one.title for one in found] == ["Leetcode"]
        assert found[0].kind is RaisedKind.OVERDUE_TASK
        assert "Overdue" in found[0].statement


class TestTheHabitCapUsesTheSameSurfaceAsAChronicSkip:
    def test_a_habit_its_own_policy_raises_becomes_a_raised_item(self) -> None:
        # `US-HAB-07`: reaching the cap raises the habit "through the same surface chronic skips
        # use", so it is a kind of raised item rather than a second mechanism. Whether it is raised
        # at all is the domain reading's answer, not a condition restated here.
        raised = a_habit(title="Gym")
        quiet = a_habit(title="Reading")
        readings = {
            raised.id: a_debt_reading(raised_in_weekly_session=True),
            quiet.id: a_debt_reading(raised_in_weekly_session=False),
        }

        found = habit_debt_items([raised, quiet], readings)

        assert [one.title for one in found] == ["Gym"]
        assert found[0].kind is RaisedKind.HABIT_AT_DEBT_CAP
        assert found[0].statement == readings[raised.id].statement

    def test_a_habit_with_no_reading_at_all_is_not_raised(self) -> None:
        assert habit_debt_items([a_habit(title="Gym")], {}) == []


class TestThePeriodStatement:
    def test_it_states_both_counts(self) -> None:
        said = period_statement(confirmed=5, unconfirmed=2, off_plan=0)

        assert "5 confirmed days" in said
        assert "2 unconfirmed" in said

    def test_off_plan_days_are_reported_separately_from_unconfirmed_ones(self) -> None:
        said = period_statement(confirmed=3, unconfirmed=1, off_plan=3)

        assert "1 unconfirmed" in said
        assert "3 declared off-plan" in said

    def test_a_period_with_no_confirmed_day_says_so_rather_than_charting_nothing(self) -> None:
        said = period_statement(confirmed=0, unconfirmed=7, off_plan=0)

        assert "No day of this period was answered for" in said
        assert "nothing to chart" in said
