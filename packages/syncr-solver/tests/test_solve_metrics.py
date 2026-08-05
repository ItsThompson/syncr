"""The four families a solve publishes, observed on the registry the application exposes.

A metric nobody observes is a dashboard row that stays empty, so each family is driven through
``solve`` rather than asserted to exist. The empty-slot family is the one worth reading twice: it
observes every reason on every solve INCLUDING zero, so a reason that stopped happening reads as a
fall rather than as a series that went absent.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from prometheus_client import generate_latest

from syncr_common.metrics import REGISTRY
from syncr_domain.gaps import EmptySlotReason
from syncr_domain.identity import BindingRef
from syncr_solver.errors import SolveError
from syncr_solver.metrics import SOLVE_FAMILIES, SolveOutcome
from tests.materialized_weeks import CAREER, a_pin, a_slot, an_area_budget, between
from tests.objective_weeks import an_eligible_task
from tests.solve_weeks import a_week, solved


def exposition() -> str:
    return generate_latest(REGISTRY).decode("utf-8")


def sample(name: str, labels: dict[str, str] | None = None) -> float:
    found = REGISTRY.get_sample_value(name, labels)
    return 0.0 if found is None else found


def test_a_solve_records_its_duration_under_the_outcome_it_reached() -> None:
    """A returning solve succeeded, which is the only outcome the placement code can observe."""
    before = sample("syncr_solve_duration_seconds_count", {"outcome": SolveOutcome.SUCCEEDED.value})

    solved(a_week(eligible_tasks=(an_eligible_task(remaining_minutes=60),)))

    assert (
        sample("syncr_solve_duration_seconds_count", {"outcome": SolveOutcome.SUCCEEDED.value})
        == before + 1
    )


def test_a_solve_that_raises_records_its_duration_under_failed_and_not_under_succeeded() -> None:
    """A failure that reads as a success is the alert inversion three tickets in this wave hit.

    A context manager around the body records on exit whether or not the body raised, so it would
    put one raise under ``succeeded`` and the coordinator would add its own ``failed``: one failure,
    two rows, two labels, and a success rate that reads high.
    """
    before = {
        outcome: sample("syncr_solve_duration_seconds_count", {"outcome": outcome.value})
        for outcome in SolveOutcome
    }
    week = a_week(pins=(a_pin(binding=BindingRef.for_habit(uuid4(), index=3)),))

    with pytest.raises(SolveError):
        solved(week)

    assert (
        sample("syncr_solve_duration_seconds_count", {"outcome": SolveOutcome.FAILED.value})
        == before[SolveOutcome.FAILED] + 1
    )
    assert (
        sample("syncr_solve_duration_seconds_count", {"outcome": SolveOutcome.SUCCEEDED.value})
        == before[SolveOutcome.SUCCEEDED]
    )


def test_a_solve_records_the_moves_it_considered_and_the_blocks_it_placed() -> None:
    before = (sample("syncr_solve_iterations_count"), sample("syncr_solve_blocks_placed_count"))

    result = solved(
        a_week(
            eligible_tasks=(an_eligible_task(remaining_minutes=60),),
            areas=(an_area_budget(target_minutes=600),),
        )
    )

    assert sample("syncr_solve_iterations_count") == before[0] + 1
    assert sample("syncr_solve_blocks_placed_count") == before[1] + 1
    assert sample("syncr_solve_blocks_placed_sum") >= len(result.document.blocks)


def test_the_empty_slot_family_observes_every_reason_including_the_ones_at_zero() -> None:
    before = {
        reason: sample("syncr_solve_empty_slots_count", {"reason": reason.value})
        for reason in EmptySlotReason
    }

    solved(
        a_week(
            template_entries=(a_slot(area_id=CAREER, interval=between(18, 19)),),
            areas=(an_area_budget(area_id=CAREER, name="Career"),),
        )
    )

    for reason in EmptySlotReason:
        found = sample("syncr_solve_empty_slots_count", {"reason": reason.value})
        assert found == before[reason] + 1, reason


def test_the_reason_a_slot_stated_is_the_one_the_family_counted() -> None:
    before = sample(
        "syncr_solve_empty_slots_sum", {"reason": EmptySlotReason.NO_ELIGIBLE_CONTENT.value}
    )

    solved(
        a_week(
            template_entries=(a_slot(area_id=CAREER, interval=between(18, 19)),),
            areas=(an_area_budget(area_id=CAREER, name="Career"),),
        )
    )

    assert (
        sample("syncr_solve_empty_slots_sum", {"reason": EmptySlotReason.NO_ELIGIBLE_CONTENT.value})
        == before + 1
    )


def test_no_solve_ever_counts_a_slot_saying_nobody_looked_at_the_backlog() -> None:
    """``not_solved`` is materialization's reason, so a solve observes it at zero forever."""
    before = sample("syncr_solve_empty_slots_sum", {"reason": EmptySlotReason.NOT_SOLVED.value})

    solved(
        a_week(
            template_entries=(a_slot(area_id=CAREER, interval=between(18, 19)),),
            areas=(an_area_budget(area_id=CAREER, name="Career"),),
        )
    )

    assert (
        sample("syncr_solve_empty_slots_sum", {"reason": EmptySlotReason.NOT_SOLVED.value})
        == before
    )


def test_the_four_families_the_module_names_are_the_four_the_exposition_carries() -> None:
    """Named in one place so a reader finds the inventory, and crossed so it cannot go stale."""
    carried = exposition()

    for family in SOLVE_FAMILIES:
        assert f"# TYPE {family} histogram" in carried, family


def test_the_reading_finds_a_family_rather_than_matching_nothing() -> None:
    # The control: a probe that found nothing would pass every assertion made over it.
    assert "# TYPE syncr_materialize_total counter" in exposition()
    assert "# TYPE syncr_not_a_family histogram" not in exposition()
