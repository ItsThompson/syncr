"""The pie review's arithmetic: the observed share, the quarter's gate, and the proposal rule."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from syncr_domain.budget_review import (
    QUARTER_WEEKS,
    WHOLE_SHARE,
    BudgetReviewError,
    ProposalBasis,
    ReviewedCategory,
    has_a_quarter_of_confirmed_data,
    observed_percent,
    proposed_share,
    proposed_shares,
    uncovered_minutes,
)
from syncr_domain.identifiers import AreaId  # noqa: TC001 - used in a runtime default


def an_area() -> AreaId:
    return uuid4()


def category(
    *,
    declared: str,
    observed: str,
    holds_a_floor: bool = False,
    weeks_short_of_target: int = 0,
    weeks_counted: int = QUARTER_WEEKS,
    area_id: AreaId | None = None,
) -> ReviewedCategory:
    """One reviewed category, defaulting to a full quarter that met its target every week."""
    return ReviewedCategory(
        area_id=an_area() if area_id is None else area_id,
        declared_percent=Decimal(declared),
        observed_percent=Decimal(observed),
        holds_a_floor=holds_a_floor,
        weeks_short_of_target=weeks_short_of_target,
        weeks_counted=weeks_counted,
    )


class TestTheObservedShare:
    """What a category held, as a share of the discretionary time it was measured against."""

    def test_it_divides_the_actual_by_the_discretionary_time(self) -> None:
        assert observed_percent(2520, 10080) == Decimal("25.0")

    def test_it_reports_a_tenth_of_a_point(self) -> None:
        # 1092 of 4000 is 27.3%, which is the figure the rendered budget sheet draws for Career.
        assert observed_percent(1092, 4000) == Decimal("27.3")

    @pytest.mark.parametrize("discretionary", [0, -60])
    def test_no_discretionary_time_observed_nothing(self, discretionary: int) -> None:
        """A week off-plan from end to end. There was nothing to observe, not a division to make."""
        assert observed_percent(600, discretionary) == Decimal(0)

    def test_nothing_covered_is_a_share_of_nothing(self) -> None:
        assert observed_percent(0, 10080) == Decimal(0)

    def test_a_share_may_exceed_the_whole(self) -> None:
        """A `moved` outcome may report time outside what the week planned. It is not clamped here.

        The figure is what happened. Clamping it would make the review propose a share from a
        number the log does not carry.
        """
        assert observed_percent(20160, 10080) == Decimal("200.0")

    def test_it_rounds_half_to_even_rather_than_away_from_zero(self) -> None:
        """3.25 of 100 is 3.25 points, which rounds DOWN to 3.2 under half-to-even."""
        assert observed_percent(325, 10000) == Decimal("3.2")
        assert observed_percent(335, 10000) == Decimal("3.4")


class TestTheVacancysMinutes:
    """Discretionary minutes no confirmed block covered, over two counts rather than two sets."""

    def test_it_is_the_denominator_less_what_was_covered(self) -> None:
        assert uncovered_minutes(10080, 2520) == 7560

    def test_nothing_covered_leaves_the_whole_denominator(self) -> None:
        assert uncovered_minutes(10080, 0) == 10080

    def test_it_is_not_zero_merely_because_the_shares_sum_to_a_hundred(self) -> None:
        """The figure is coverage, never a residual against the targets. A budget summing to 100 has
        no bearing on it: what decides it is how many minutes sat in a block."""
        assert uncovered_minutes(10080, 6000) == 4080

    def test_coverage_past_the_denominator_is_not_a_negative_vacancy(self) -> None:
        """A `moved` outcome reporting time inside the frame. The clamp's one reachable case."""
        assert uncovered_minutes(6720, 7000) == 0


class TestTheQuartersGate:
    """Whether enough confirmed weeks exist for a proposal to say anything."""

    @pytest.mark.parametrize("weeks", [0, 1, 12])
    def test_fewer_than_thirteen_weeks_is_not_a_quarter(self, weeks: int) -> None:
        assert not has_a_quarter_of_confirmed_data(weeks)

    @pytest.mark.parametrize("weeks", [13, 14, 52])
    def test_thirteen_weeks_or_more_is_a_quarter(self, weeks: int) -> None:
        assert has_a_quarter_of_confirmed_data(weeks)

    def test_a_quarter_is_thirteen_weeks(self) -> None:
        """Stated from both sides, so retuning the gate moves one constant."""
        assert QUARTER_WEEKS == 13
        assert has_a_quarter_of_confirmed_data(QUARTER_WEEKS)
        assert not has_a_quarter_of_confirmed_data(QUARTER_WEEKS - 1)


class TestTheProposalRule:
    """The declared share moved by half the distance to the observed one, truncated toward zero."""

    def test_it_moves_half_way_toward_a_lower_observed_share(self) -> None:
        # 30 declared, 27.3 observed: half of the 2.7-point gap is 1.35, truncated to 1.
        proposed = proposed_share(category(declared="30", observed="27.3"))
        assert proposed.proposed_percent == Decimal(29)

    def test_it_moves_half_way_toward_a_higher_observed_share(self) -> None:
        # 15 declared, 35.3 observed: half of the 20.3-point gap is 10.15, truncated to 10. The
        # vacancy's own row in the rendered review, whose figure is 25.
        proposed = proposed_share(category(declared="15", observed="35.3"))
        assert proposed.proposed_percent == Decimal(25)

    def test_it_never_reaches_the_observed_share(self) -> None:
        """Half the distance, not the whole of it: a budget that ratifies the past cannot starve."""
        proposed = proposed_share(category(declared="40", observed="0"))
        assert proposed.proposed_percent == Decimal(20)

    def test_a_gap_under_two_points_moves_nothing(self) -> None:
        """The property truncating the DISTANCE buys, and the reason the midpoint is not truncated.

        Truncating the midpoint would propose 19 here, off a gap of a tenth of a point, and 19 is
        further from the observation than 20 was.
        """
        assert proposed_share(category(declared="20", observed="19.9")).proposed_percent == Decimal(
            20
        )
        assert proposed_share(category(declared="20", observed="21.9")).proposed_percent == Decimal(
            20
        )

    def test_it_truncates_the_distance_rather_than_rounding_it(self) -> None:
        # 10 declared, 2.9 observed: half the gap is 3.55, truncated to 3. Rounding would give 4.
        under = proposed_share(category(declared="10", observed="2.9"))
        assert under.proposed_percent == Decimal(7)
        # 10 declared, 17.4 observed: half the gap is 3.7, truncated to 3. Rounding would give 4.
        assert proposed_share(category(declared="10", observed="17.4")).proposed_percent == Decimal(
            13
        )

    def test_it_carries_the_declared_and_observed_figures_through(self) -> None:
        proposed = proposed_share(category(declared="30", observed="27.3"))
        assert proposed.declared_percent == Decimal(30)
        assert proposed.observed_percent == Decimal("27.3")

    def test_a_share_cannot_be_proposed_below_zero(self) -> None:
        """Unreachable from a real observation, and the bound is stated rather than assumed."""
        proposed = proposed_share(category(declared="0", observed="-10"))
        assert proposed.proposed_percent == Decimal(0)

    def test_a_share_is_not_proposed_past_the_whole(self) -> None:
        proposed = proposed_share(category(declared="120", observed="200"))
        assert proposed.proposed_percent == WHOLE_SHARE

    def test_an_oversubscribed_declaration_is_proposed_down_rather_than_refused(self) -> None:
        proposed = proposed_share(category(declared="130", observed="30"))
        assert proposed.proposed_percent == Decimal(80)
        assert proposed.basis is ProposalBasis.SUSTAINED_UNDER

    @given(
        declared=st.decimals(min_value=0, max_value=100, places=0),
        observed=st.decimals(min_value=0, max_value=100, places=1),
    )
    def test_a_proposal_never_passes_the_share_it_moves_toward(
        self, declared: Decimal, observed: Decimal
    ) -> None:
        """It lies between the declaration and the observation, inclusive of both ends."""
        proposed = proposed_share(
            category(declared=str(declared), observed=str(observed))
        ).proposed_percent
        assert min(declared, observed) <= proposed <= max(declared, observed)

    def test_every_category_keeps_its_own_identity(self) -> None:
        first, second = an_area(), an_area()
        proposals = proposed_shares(
            [
                category(declared="30", observed="27.3", area_id=first),
                category(declared="10", observed="2.9", area_id=second),
            ]
        )
        assert [proposal.area_id for proposal in proposals] == [first, second]

    def test_nothing_reviewed_proposes_nothing(self) -> None:
        assert proposed_shares([]) == ()


class TestTheVacancy:
    """Discretionary time no block covered is a row like any Area, and takes the same rule."""

    def test_it_carries_no_area_and_is_still_proposed_for(self) -> None:
        proposed = proposed_share(
            ReviewedCategory(
                area_id=None,
                declared_percent=Decimal(15),
                observed_percent=Decimal("35.3"),
                holds_a_floor=False,
                weeks_short_of_target=0,
                weeks_counted=QUARTER_WEEKS,
            )
        )
        assert proposed.area_id is None
        assert proposed.proposed_percent == Decimal(25)
        assert proposed.basis is ProposalBasis.SUSTAINED_OVER


class TestTheBasis:
    """Why a proposal is what it is, in the order the reasons outrank each other."""

    def test_a_floor_leaves_the_share_alone(self) -> None:
        """The share divides what the floors leave, so it is not the figure holding that time."""
        proposed = proposed_share(
            category(declared="12", observed="8.6", holds_a_floor=True, weeks_short_of_target=13)
        )
        assert proposed.basis is ProposalBasis.FLOOR_HOLDS_IT
        assert proposed.proposed_percent == Decimal(12)

    def test_a_floor_outranks_a_target_missed_every_week(self) -> None:
        """Stated as a precedence rather than as two independent cases."""
        missed_everywhere = category(
            declared="12", observed="0", weeks_short_of_target=13, weeks_counted=13
        )
        assert proposed_share(missed_everywhere).basis is ProposalBasis.NEVER_MET
        with_a_floor = ReviewedCategory(
            area_id=missed_everywhere.area_id,
            declared_percent=missed_everywhere.declared_percent,
            observed_percent=missed_everywhere.observed_percent,
            holds_a_floor=True,
            weeks_short_of_target=missed_everywhere.weeks_short_of_target,
            weeks_counted=missed_everywhere.weeks_counted,
        )
        assert proposed_share(with_a_floor).basis is ProposalBasis.FLOOR_HOLDS_IT

    def test_a_share_already_at_its_observation_moves_nothing(self) -> None:
        proposed = proposed_share(
            category(declared="20", observed="20", weeks_short_of_target=0, weeks_counted=13)
        )
        assert proposed.basis is ProposalBasis.ALREADY_THERE
        assert proposed.proposed_percent == Decimal(20)

    def test_a_share_whose_half_distance_truncates_to_nothing_moves_nothing(self) -> None:
        """20 declared, 21 observed: half the one-point gap is 0.5 and truncates to nothing."""
        proposed = proposed_share(category(declared="20", observed="21"))
        assert proposed.proposed_percent == Decimal(20)
        assert proposed.basis is ProposalBasis.ALREADY_THERE

    def test_an_unmoved_proposal_outranks_a_target_missed_every_week(self) -> None:
        proposed = proposed_share(
            category(declared="20", observed="19.9", weeks_short_of_target=13, weeks_counted=13)
        )
        assert proposed.basis is ProposalBasis.ALREADY_THERE

    def test_a_target_missed_in_every_counted_week_says_so(self) -> None:
        proposed = proposed_share(
            category(declared="10", observed="2.9", weeks_short_of_target=13, weeks_counted=13)
        )
        assert proposed.basis is ProposalBasis.NEVER_MET

    def test_a_target_missed_in_all_but_one_week_is_sustained_rather_than_never_met(self) -> None:
        proposed = proposed_share(
            category(declared="10", observed="2.9", weeks_short_of_target=12, weeks_counted=13)
        )
        assert proposed.basis is ProposalBasis.SUSTAINED_UNDER

    def test_no_counted_week_cannot_have_missed_every_one(self) -> None:
        """Zero of zero weeks is vacuously every week. Reporting it as never met would be a
        statement about a period that observed nothing."""
        proposed = proposed_share(
            category(declared="10", observed="0", weeks_short_of_target=0, weeks_counted=0)
        )
        assert proposed.basis is ProposalBasis.SUSTAINED_UNDER

    def test_a_share_observed_above_its_target_reads_as_over(self) -> None:
        proposed = proposed_share(category(declared="10", observed="30"))
        assert proposed.basis is ProposalBasis.SUSTAINED_OVER

    def test_every_reason_is_reachable(self) -> None:
        """The vocabulary is bounded by the enum, so a member nothing produces is dead."""
        produced = {
            proposed_share(one).basis
            for one in [
                category(declared="12", observed="8.6", holds_a_floor=True),
                category(declared="10", observed="2.9", weeks_short_of_target=13),
                category(declared="10", observed="2.9", weeks_short_of_target=12),
                category(declared="10", observed="30"),
                category(declared="20", observed="20"),
            ]
        }
        assert produced == set(ProposalBasis)


class TestARefusedCategory:
    """A count that is not a count, refused where it is stated rather than where it divides."""

    def test_a_negative_week_count_is_refused(self) -> None:
        with pytest.raises(BudgetReviewError, match="not a count of weeks"):
            category(declared="10", observed="10", weeks_counted=-1)

    def test_more_weeks_short_than_were_counted_is_refused(self) -> None:
        with pytest.raises(BudgetReviewError, match="more weeks than were counted"):
            category(declared="10", observed="10", weeks_short_of_target=14, weeks_counted=13)

    def test_a_negative_count_of_short_weeks_is_refused(self) -> None:
        with pytest.raises(BudgetReviewError, match="more weeks than were counted"):
            category(declared="10", observed="10", weeks_short_of_target=-1, weeks_counted=13)
