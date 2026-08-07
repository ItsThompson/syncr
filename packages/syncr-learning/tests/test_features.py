"""The three exclusions, the two hours a block has, and what each observation kind is derived from.

Every test here is literals in and counts out. An exclusion is asserted as an observation count of
zero rather than as a fitted value equal to a prior, because a prior is a figure the fitter would
also produce from a corpus it read and refused: the count is what says the row never reached it.
"""

from __future__ import annotations

from datetime import timedelta

from syncr_domain.intervals import Interval
from syncr_domain.outcomes import OutcomeState
from syncr_domain.weeks import IsoWeek
from syncr_learning.config import TimeBucket
from syncr_learning.features import extract
from tests.builders import (
    AREA,
    OTHER_AREA,
    WEEK,
    a_week_of,
    at,
    corpus,
    edit,
    off_plan,
    outcome,
    planned,
    revision,
    span,
)


class TestUnconfirmedDaysAreExcludedFromEveryFitter:
    def test_a_confirmed_partial_produces_a_duration_observation(self) -> None:
        observed = extract(a_week_of(1, state=OutcomeState.PARTIAL, actual_minutes=82))

        assert len(observed.durations) == 1
        assert observed.durations[0].actual_minutes == 82

    def test_the_same_row_unconfirmed_produces_nothing_at_all(self) -> None:
        observed = extract(
            a_week_of(1, state=OutcomeState.PARTIAL, actual_minutes=82, is_confirmed=False)
        )

        assert observed.total() == 0

    def test_a_block_with_no_outcome_row_produces_nothing(self) -> None:
        # The absence of a row is presumed AND unconfirmed. Read as a completion it would count a
        # day the user never answered for, which is the exact failure the rule exists to prevent.
        observed = extract(corpus(revisions=[revision(blocks=[planned()])], outcomes=[]))

        assert observed.total() == 0


class TestOffPlanSpansAreExcludedWholesale:
    def test_a_confirmed_block_inside_a_declared_span_raises_no_sample_count(self) -> None:
        # Confirmation does not rescue it. The rule is unconditional, which is what makes "what
        # counts" one sentence on the Learned screen.
        inside = a_week_of(5, state=OutcomeState.PARTIAL, actual_minutes=82, hour=9)
        with_span = corpus(
            revisions=inside.revisions,
            outcomes=inside.outcomes,
            spans=[off_plan(day=0, days=1)],
        )

        assert extract(with_span).total() == 0
        assert extract(inside).total() > 0

    def test_a_block_only_partly_inside_a_span_is_still_excluded(self) -> None:
        # Overlap rather than containment: a block half inside a holiday was half lived under a
        # different regime, and a rule that counted it would have to say which half.
        block = planned(interval=Interval(at(day=0, hour=23), at(day=1, hour=1)))
        touching = corpus(
            revisions=[revision(blocks=[block])],
            outcomes=[outcome(state=OutcomeState.COMPLETED)],
            spans=[off_plan(day=1, days=1)],
        )

        assert extract(touching).total() == 0

    def test_an_edit_flagged_inside_an_off_plan_span_is_excluded_from_the_ranking(self) -> None:
        difference = dict.fromkeys(_TERMS, -1.0)
        flagged = corpus(edits=[edit(difference=difference, inside_off_plan=True)])

        assert extract(flagged).ranking == ()

    def test_an_edit_inside_a_span_declared_since_is_excluded_even_unflagged(self) -> None:
        # An older row's flag cannot know about a span declared afterwards, so both are checked.
        difference = dict.fromkeys(_TERMS, -1.0)
        later = corpus(
            edits=[edit(difference=difference, accepted=span(day=2, hour=13))],
            spans=[off_plan(day=2, days=1)],
        )

        assert extract(later).ranking == ()


class TestACorrectedConfirmationIsRefittedFromTheLog:
    def test_correcting_one_row_changes_the_observation_the_next_run_derives(self) -> None:
        # Structural rather than a filter: nothing is carried between runs, so a corrected row
        # produces a corrected observation with no invalidation step and no cache to go stale.
        before = a_week_of(1, state=OutcomeState.PARTIAL, actual_minutes=82)
        corrected = corpus(
            revisions=before.revisions,
            outcomes=[outcome(state=OutcomeState.PARTIAL, actual_minutes=45)],
        )

        assert extract(before).durations[0].actual_minutes == 82
        assert extract(corrected).durations[0].actual_minutes == 45

    def test_correcting_a_completion_to_a_skip_moves_the_signal_between_fitters(self) -> None:
        done = a_week_of(1, state=OutcomeState.COMPLETED, actual_minutes=None)
        skipped = corpus(revisions=done.revisions, outcomes=[outcome(state=OutcomeState.SKIPPED)])

        assert extract(done).time_of_day[0].went_well is True
        assert extract(skipped).time_of_day[0].went_well is False
        assert extract(done).skips[0].was_refused is False
        assert extract(skipped).skips[0].was_refused is True


class TestTheTwoHoursABlockHas:
    def test_a_moved_block_reads_its_fitness_at_the_hour_it_really_happened(self) -> None:
        block = planned(interval=span(hour=7))
        moved_to = Interval(at(hour=19), at(hour=19) + timedelta(minutes=60))
        observed = extract(
            corpus(
                revisions=[revision(blocks=[block])],
                outcomes=[outcome(state=OutcomeState.MOVED, actual=moved_to)],
            )
        )

        assert observed.time_of_day[0].hour == 19

    def test_the_same_moved_block_reads_its_skip_bucket_at_the_hour_it_was_planned(self) -> None:
        # A skip probability answers "would the user refuse work put here", and "here" is where the
        # solver would be putting it. Reading the actual hour would answer a different question.
        block = planned(interval=span(hour=7))
        moved_to = Interval(at(hour=19), at(hour=19) + timedelta(minutes=60))
        observed = extract(
            corpus(
                revisions=[revision(blocks=[block])],
                outcomes=[outcome(state=OutcomeState.MOVED, actual=moved_to)],
            )
        )

        assert observed.skips[0].bucket is TimeBucket.MORNING
        assert observed.skips[0].was_refused is True

    def test_the_hour_is_local_to_the_zone_the_plan_captured(self) -> None:
        # 09:00 UTC is 11:00 in Athens. A run that read UTC would fit a curve two hours off for
        # every week the user spent there.
        travelled = revision(
            blocks=[planned(interval=span(hour=9))],
            zone_by_date=dict.fromkeys(WEEK.dates(), "Europe/Athens"),
        )
        observed = extract(
            corpus(revisions=[travelled], outcomes=[outcome(state=OutcomeState.COMPLETED)])
        )

        assert observed.time_of_day[0].hour == 11


class TestWhatEachObservationKindNeeds:
    def test_only_a_partial_produces_a_duration_observation(self) -> None:
        for state in OutcomeState:
            minutes = 82 if state is OutcomeState.PARTIAL else None
            actual = Interval(at(hour=9), at(hour=10)) if state is OutcomeState.MOVED else None
            observed = extract(
                corpus(
                    revisions=[revision(blocks=[planned()])],
                    outcomes=[outcome(state=state, actual_minutes=minutes, actual=actual)],
                )
            )
            expected = 1 if state is OutcomeState.PARTIAL else 0
            assert len(observed.durations) == expected, state

    def test_a_block_with_no_area_produces_no_observation(self) -> None:
        # Every parameter fitted from a block is keyed on an Area, and the frame and the imported
        # commitments carry none.
        observed = extract(
            corpus(
                revisions=[revision(blocks=[planned(area_id=None)])],
                outcomes=[outcome(state=OutcomeState.COMPLETED)],
            )
        )

        assert observed.total() == 0

    def test_adjacent_blocks_produce_a_switch_observation_carrying_the_gap(self) -> None:
        first = planned(index=0, area_id=AREA, interval=span(hour=9, minutes=60))
        second = planned(index=1, area_id=OTHER_AREA, interval=span(hour=11, minutes=60))
        observed = extract(
            corpus(
                revisions=[revision(blocks=[first, second])],
                outcomes=[outcome(index=0), outcome(index=1)],
            )
        )

        assert len(observed.switches) == 1
        assert observed.switches[0].gap_minutes == 60
        assert observed.switches[0].changed_area is True

    def test_a_pair_more_than_a_day_apart_is_not_adjacency(self) -> None:
        # A night's sleep leaves hours of room, and the solver's own term says a gap that long
        # absorbs any price: counting it would swamp the difference the price is measured as.
        first = planned(index=0, interval=span(day=0, hour=9))
        second = planned(index=1, interval=span(day=3, hour=9))
        observed = extract(
            corpus(
                revisions=[revision(blocks=[first, second])],
                outcomes=[outcome(index=0), outcome(index=1)],
            )
        )

        assert observed.switches == ()

    def test_only_the_latest_revision_of_a_week_supplies_lived_blocks(self) -> None:
        # An earlier revision is a proposal the week moved past, so counting its blocks would fit
        # against an arrangement the user never lived.
        superseded = revision(
            blocks=[planned(index=0, interval=span(hour=6))], created_at=at(hour=1)
        )
        current = revision(blocks=[planned(index=0, interval=span(hour=15))], created_at=at(hour=2))
        observed = extract(
            corpus(
                revisions=[superseded, current],
                outcomes=[outcome(state=OutcomeState.COMPLETED)],
            )
        )

        assert len(observed.time_of_day) == 1
        assert observed.time_of_day[0].hour == 15


class TestBackfilledConfirmationsCountIdentically:
    def test_a_day_where_everything_was_skipped_advances_the_counts_like_a_perfect_day(
        self,
    ) -> None:
        # Unlocks depend on confirmed volume, never on adherence: tying them to adherence would
        # reward marking things done, and the whole dataset's integrity rests on honest
        # confirmation.
        perfect = extract(a_week_of(9, state=OutcomeState.COMPLETED, actual_minutes=None))
        skipped = extract(a_week_of(9, state=OutcomeState.SKIPPED, actual_minutes=None))

        assert len(perfect.time_of_day) == len(skipped.time_of_day)
        assert len(perfect.skips) == len(skipped.skips)
        assert len(perfect.switches) == len(skipped.switches)

    def test_nothing_in_the_corpus_records_how_late_a_confirmation_arrived(self) -> None:
        # The structural half: a logged outcome has no field a gate could read to tell a backfilled
        # confirmation from a same-day one, so no gate here can penalise the honest late answer.
        assert "confirmed_at" not in outcome().__slots__
        assert set(outcome().__slots__) == {
            "block_id",
            "state",
            "actual_minutes",
            "actual",
            "is_confirmed",
        }


class TestSeveralWeeks:
    def test_two_weeks_of_the_same_area_accumulate(self) -> None:
        first = a_week_of(6, iso_week=WEEK)
        second = a_week_of(6, iso_week=IsoWeek(year=2026, week=8))
        both = corpus(
            revisions=[*first.revisions, *second.revisions],
            outcomes=[*first.outcomes, *second.outcomes],
        )

        assert len(extract(both).durations) == 12


_TERMS = (
    "deadline_risk",
    "budget_deviation",
    "time_of_day_misfit",
    "fragmentation",
    "churn",
    "context_switch",
    "staleness",
)
