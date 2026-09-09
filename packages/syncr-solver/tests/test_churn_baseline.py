"""The churn baseline's three readable states and the pairing it refuses."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from syncr_domain.plan import PlanDocument, PlanError
from syncr_domain.weeks import IsoWeek
from syncr_solver.churn_baseline import ChurnBaseline

WEEK = IsoWeek(2026, 7)
LONDON = "Europe/London"
NOW = datetime(2026, 2, 11, 9, 0, tzinfo=UTC)


def test_a_week_that_has_never_been_approved_states_that_rather_than_naming_a_revision() -> None:
    baseline = ChurnBaseline.never_approved()

    assert baseline.reason == ChurnBaseline.NEVER_APPROVED
    assert baseline.revision_id is None
    assert baseline.approved_at is None


def test_an_approved_baseline_names_the_revision_and_when_it_was_approved() -> None:
    identifier = uuid4()
    baseline = ChurnBaseline.approved(identifier, NOW)

    assert baseline.revision_id == identifier
    assert baseline.approved_at == NOW


def test_a_baseline_naming_a_revision_whose_plan_it_cannot_read_says_which_state_it_is_in() -> None:
    # The state a week is in when its approved document cannot be rebuilt. It is named rather than
    # reported as an ordinary approved baseline: a renderer told "approved-revision" would claim a
    # comparison against a plan nobody supplied.
    named = ChurnBaseline.approved(uuid4(), NOW)

    assert named.reason == ChurnBaseline.APPROVED_UNREADABLE
    assert named.is_measured is False


@pytest.mark.parametrize(
    ("revision_id", "approved_at"),
    [("an id", None), (None, NOW)],
    ids=["a revision with no instant", "an instant with no revision"],
)
def test_half_a_baseline_renders_half_a_sentence(
    revision_id: str | None, approved_at: object
) -> None:
    """The domain twin's rule, on this type too: the clause renders the date beside the revision."""
    with pytest.raises(PlanError, match="or neither"):
        ChurnBaseline(
            revision_id=None if revision_id is None else uuid4(),
            approved_at=approved_at,  # type: ignore[arg-type]
        )


def test_a_plan_no_revision_names_is_not_a_baseline() -> None:
    """The state a ``dominant`` clause citing churn could not render, so the type refuses it.

    ``is_measured`` reads the document, so a plan carried without a revision would make churn
    chargeable while ``reason`` still read ``never-approved``, and the clause would say the plan
    moved while naming nothing it moved from.
    """
    with pytest.raises(PlanError, match="names the revision that plan is"):
        ChurnBaseline(document=a_plan())


def test_an_approved_baseline_carrying_its_plan_is_what_churn_is_measured_against() -> None:
    # The other half of the guard above: the reachable three-field state is accepted.
    measured = ChurnBaseline.approved(uuid4(), NOW, a_plan())

    assert measured.reason == ChurnBaseline.APPROVED_REVISION
    assert measured.is_measured is True


def a_plan() -> PlanDocument:
    """An empty document of this week, for the baseline that carries one."""
    return PlanDocument(
        iso_week=WEEK,
        zone_by_date=dict.fromkeys(WEEK.dates(), LONDON),
        discretionary_minutes=0,
        unallocated_minutes=0,
        oversubscription_minutes=0,
    )
