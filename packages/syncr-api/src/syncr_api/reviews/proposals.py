"""The proposal half of the review: what the confirmed weeks observed, and what to declare.

**Only a fully confirmed week is evidence.** ``ReviewedWeek.is_fully_confirmed`` is that rule and
it states its own reason: a partly confirmed week reports actuals over some days against a
denominator over all seven, so its observed share is understated by exactly the days nobody
answered for. Proposing from that figure reads a lapse in confirming as a change in behaviour.

**Until a quarter of such weeks exists there is no proposal at all**, and the review says so.
Before a quarter of confirmed data exists, the review shows the gap only and states that proposals
need more data. The gap is the deviation chart, which
this module has no part in, so a period below the gate simply carries no shares.

**The observed share is one ratio over the whole quarter, not the mean of thirteen ratios.** A week
with a small denominator would otherwise weigh as much as a full one, so a fortnight of travel
would move a quarter's budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.reviews.figures import actual_minutes, targets, vacancy_minutes, vacancy_share
from syncr_domain.budget_review import (
    QUARTER_WEEKS,
    ProposedShare,
    ReviewedCategory,
    has_a_quarter_of_confirmed_data,
    observed_percent,
    proposed_shares,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_api.reviews.history import ReviewedWeek
    from syncr_domain.budgets import AreaShare


@dataclass(frozen=True, slots=True, kw_only=True)
class ProposalReading:
    """The proposed revision, or the count that says why there is not one yet.

    ``shares`` is empty exactly when ``confirmed_weeks`` is below ``required_weeks``. The two are
    reported together because the count is the answer to "why is this empty", and a client that had
    to infer it from an empty list would be inferring it.
    """

    confirmed_weeks: int
    required_weeks: int
    shares: tuple[ProposedShare, ...]

    @property
    def is_proposed(self) -> bool:
        """Whether a quarter of confirmed weeks exists for the proposal to rest on."""
        return has_a_quarter_of_confirmed_data(self.confirmed_weeks)


def proposal_over(
    quarter: Sequence[ReviewedWeek], *, shares: Sequence[AreaShare]
) -> ProposalReading:
    """The revision the quarter's fully confirmed weeks propose, if there are enough of them."""
    evidence = [week for week in quarter if week.is_fully_confirmed]
    counted = len(evidence)
    if not has_a_quarter_of_confirmed_data(counted):
        return ProposalReading(confirmed_weeks=counted, required_weeks=QUARTER_WEEKS, shares=())
    return ProposalReading(
        confirmed_weeks=counted,
        required_weeks=QUARTER_WEEKS,
        shares=proposed_shares(_categories(evidence, shares=shares)),
    )


def _categories(
    evidence: Sequence[ReviewedWeek], *, shares: Sequence[AreaShare]
) -> tuple[ReviewedCategory, ...]:
    """One reviewed category per Area, then the vacancy, over the confirmed weeks' own totals."""
    discretionary = sum(week.discretionary_minutes or 0 for week in evidence)
    per_week_targets = [targets(week, shares) for week in evidence]
    return (
        *(
            ReviewedCategory(
                area_id=share.area_id,
                declared_percent=share.budget_percent,
                observed_percent=observed_percent(
                    sum(actual_minutes(week, share.area_id) for week in evidence), discretionary
                ),
                holds_a_floor=share.floor_minutes > 0,
                weeks_short_of_target=sum(
                    1
                    for week, declared in zip(evidence, per_week_targets, strict=True)
                    if actual_minutes(week, share.area_id) < declared.get(share.area_id, 0)
                ),
                weeks_counted=len(evidence),
            )
            for share in shares
        ),
        ReviewedCategory(
            area_id=None,
            declared_percent=vacancy_share(shares),
            observed_percent=observed_percent(
                sum(vacancy_minutes(week) or 0 for week in evidence), discretionary
            ),
            holds_a_floor=False,
            weeks_short_of_target=0,
            weeks_counted=len(evidence),
        ),
    )
