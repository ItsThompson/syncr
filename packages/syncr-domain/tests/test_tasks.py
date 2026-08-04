"""Task physics: T1, T3, T4, the endings, and the defaults capture leans on.

Each invariant is asserted at its boundary rather than only in its middle, because every one
of them is an inequality and an inequality is wrong at exactly one value. T1 is checked at
equal, one under, and one over; T3 at recorded equal to the estimate and one minute past it;
eligibility at one remaining minute and at zero.

The defaults are asserted as DERIVATIONS rather than as literals wherever they are one. The
minimum chunk is the grid step and the estimate is two of them, so a retune of the grid moves
both together and a test comparing them against ``15`` and ``30`` would be the second place
the grid is stated.
"""

from __future__ import annotations

import pytest

from syncr_domain.snap import SNAP_MINUTES
from syncr_domain.tasks import (
    DEFAULT_ESTIMATE_MINUTES,
    DEFAULT_MIN_CHUNK_MINUTES,
    DEFAULT_PRIORITY,
    DEFAULT_SPLITTABLE,
    NO_RECORDED_MINUTES,
    ChunkLargerThanEstimate,
    Priority,
    TaskAlreadyEnded,
    TaskEnding,
    TaskStatus,
    default_min_chunk_minutes,
    is_eligible_for_solving,
    remaining_minutes,
    require_a_chunk_that_fits,
    require_a_compatible_ending,
)

AN_HOUR = 60


# --------------------------------------------------------------------------------
# The vocabularies
# --------------------------------------------------------------------------------


def test_the_status_vocabulary_is_the_three_the_domain_model_names() -> None:
    assert [status.value for status in TaskStatus] == ["open", "completed", "dropped"]


def test_the_priority_vocabulary_is_the_four_the_domain_model_names_in_order() -> None:
    # Ordered least to most urgent, which is the order the interface renders and the order a
    # later objective term reads. Asserted because the members' declaration order is the only
    # statement of it.
    assert [priority.value for priority in Priority] == ["low", "normal", "high", "urgent"]


def test_a_status_and_a_priority_render_as_their_own_value_on_the_wire() -> None:
    # `StrEnum`, so a schema serializes the member's value rather than `TaskStatus.OPEN`.
    assert f"{TaskStatus.OPEN}" == "open"
    assert f"{Priority.URGENT}" == "urgent"


# --------------------------------------------------------------------------------
# T1: a minimum chunk fits inside the estimate
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("estimate", "minimum"),
    [(AN_HOUR, AN_HOUR), (AN_HOUR, AN_HOUR - 1), (AN_HOUR, 1)],
    ids=["a chunk that is the whole estimate", "one minute under", "one minute"],
)
def test_a_chunk_that_fits_is_accepted(estimate: int, minimum: int) -> None:
    require_a_chunk_that_fits(estimate_minutes=estimate, min_chunk_minutes=minimum)


def test_a_chunk_one_minute_larger_than_the_estimate_is_refused() -> None:
    # One minute over, not an obvious value: the rule is an inequality and an inequality is
    # wrong at exactly one place.
    with pytest.raises(ChunkLargerThanEstimate) as rejected:
        require_a_chunk_that_fits(estimate_minutes=AN_HOUR, min_chunk_minutes=AN_HOUR + 1)

    # The reason travels with the rejection, because the boundary states it to the caller.
    assert "61" in str(rejected.value)
    assert "60" in str(rejected.value)


def test_the_rejection_is_a_domain_error_so_the_boundary_can_map_it_once() -> None:
    with pytest.raises(ValueError, match="does not fit"):
        require_a_chunk_that_fits(estimate_minutes=15, min_chunk_minutes=30)


# --------------------------------------------------------------------------------
# T3: remaining work, never negative
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("estimate", "recorded", "expected"),
    [
        (AN_HOUR, 0, AN_HOUR),
        (AN_HOUR, 25, 35),
        (AN_HOUR, AN_HOUR, 0),
        (AN_HOUR, AN_HOUR + 1, 0),
        (AN_HOUR, AN_HOUR * 3, 0),
    ],
    ids=[
        "nothing recorded",
        "partially recorded",
        "recorded exactly the estimate",
        "one minute past the estimate",
        "far past the estimate",
    ],
)
def test_remaining_work_is_the_estimate_less_what_was_recorded_and_never_negative(
    estimate: int, recorded: int, expected: int
) -> None:
    assert remaining_minutes(estimate_minutes=estimate, recorded_minutes=recorded) == expected


def test_a_partially_recorded_task_reduces_its_remaining_estimate_rather_than_its_record() -> None:
    # US-TASK-04's last criterion, as arithmetic: the recorded figure is an input to this and
    # is never rewritten by it, so the time already spent survives for reports.
    estimate, recorded = 90, 30

    assert remaining_minutes(estimate_minutes=estimate, recorded_minutes=recorded) == 60
    assert remaining_minutes(estimate_minutes=estimate, recorded_minutes=recorded) < estimate


# --------------------------------------------------------------------------------
# T4 and eligibility
# --------------------------------------------------------------------------------


def test_an_open_task_with_work_left_is_eligible() -> None:
    assert is_eligible_for_solving(status=TaskStatus.OPEN, remaining_minutes=1) is True


def test_an_open_task_with_nothing_left_is_not_eligible() -> None:
    # Zero, not negative: `remaining_minutes` clamps, so zero is what "nothing left" looks
    # like however much was recorded.
    assert is_eligible_for_solving(status=TaskStatus.OPEN, remaining_minutes=0) is False


@pytest.mark.parametrize("status", [TaskStatus.COMPLETED, TaskStatus.DROPPED])
def test_a_task_that_ended_is_not_eligible_however_much_work_it_still_declares(
    status: TaskStatus,
) -> None:
    # T4. The estimate is untouched by completing, so a completed task still declares work; it
    # is the status that ends eligibility, immediately and with no separate signal.
    assert is_eligible_for_solving(status=status, remaining_minutes=AN_HOUR) is False


def test_exactly_one_status_is_eligible() -> None:
    # The control on the two tests above: a predicate that answered True for everything would
    # pass the open case, and one that answered False for everything would pass both ended
    # cases.
    eligible = [
        status
        for status in TaskStatus
        if is_eligible_for_solving(status=status, remaining_minutes=AN_HOUR)
    ]

    assert eligible == [TaskStatus.OPEN]


# --------------------------------------------------------------------------------
# The two endings
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("ending", [TaskStatus.COMPLETED, TaskStatus.DROPPED])
def test_an_open_task_can_end_either_way(ending: TaskEnding) -> None:
    require_a_compatible_ending(current=TaskStatus.OPEN, ending=ending)


@pytest.mark.parametrize("ending", [TaskStatus.COMPLETED, TaskStatus.DROPPED])
def test_ending_a_task_the_way_it_already_ended_is_allowed_and_says_nothing(
    ending: TaskEnding,
) -> None:
    # What makes a retried request safe: the caller asked for the state the task is already in,
    # so there is nothing to refuse and nothing to change.
    require_a_compatible_ending(current=ending, ending=ending)


@pytest.mark.parametrize(
    ("current", "ending"),
    [
        (TaskStatus.COMPLETED, TaskStatus.DROPPED),
        (TaskStatus.DROPPED, TaskStatus.COMPLETED),
    ],
    ids=["dropping a completed task", "completing a dropped task"],
)
def test_crossing_between_the_two_endings_is_refused_and_says_which(
    current: TaskStatus, ending: TaskEnding
) -> None:
    with pytest.raises(TaskAlreadyEnded) as refused:
        require_a_compatible_ending(current=current, ending=ending)

    assert current.value in str(refused.value)
    assert ending.value in str(refused.value)


# --------------------------------------------------------------------------------
# The capture defaults
# --------------------------------------------------------------------------------


def test_the_default_minimum_chunk_is_the_grid_step() -> None:
    # Derived, not chosen: the grid cannot draw an interval shorter than one step, and a larger
    # default would invent a constraint the user never stated.
    assert DEFAULT_MIN_CHUNK_MINUTES == SNAP_MINUTES


def test_the_default_estimate_is_two_grid_steps_so_a_captured_task_can_actually_split() -> None:
    assert DEFAULT_ESTIMATE_MINUTES == 2 * SNAP_MINUTES
    assert DEFAULT_ESTIMATE_MINUTES // DEFAULT_MIN_CHUNK_MINUTES == 2


def test_the_defaults_satisfy_t1_between_themselves() -> None:
    # The one pair every capture that states nothing but a title and an Area produces. A pair
    # that violated T1 would make the documented default unusable.
    require_a_chunk_that_fits(
        estimate_minutes=DEFAULT_ESTIMATE_MINUTES, min_chunk_minutes=DEFAULT_MIN_CHUNK_MINUTES
    )


def test_a_captured_task_is_immediately_eligible_under_the_defaults() -> None:
    # US-TASK-01's last criterion, at the level the predicate is stated: a task captured with
    # nothing but a title and an Area has work left and is open, so the next assembly sees it.
    assert is_eligible_for_solving(
        status=TaskStatus.OPEN,
        remaining_minutes=remaining_minutes(
            estimate_minutes=DEFAULT_ESTIMATE_MINUTES, recorded_minutes=NO_RECORDED_MINUTES
        ),
    )


def test_the_remaining_defaults_are_the_ones_capture_documents() -> None:
    assert DEFAULT_PRIORITY is Priority.NORMAL
    assert DEFAULT_SPLITTABLE is True
    assert NO_RECORDED_MINUTES == 0


@pytest.mark.parametrize(
    ("estimate", "expected"),
    [
        (SNAP_MINUTES * 4, SNAP_MINUTES),
        (SNAP_MINUTES, SNAP_MINUTES),
        (SNAP_MINUTES - 1, SNAP_MINUTES - 1),
        (1, 1),
    ],
    ids=[
        "an estimate above the grid step",
        "an estimate of exactly one step",
        "an estimate one minute under a step",
        "a one-minute estimate",
    ],
)
def test_the_default_chunk_is_clamped_down_to_a_smaller_stated_estimate(
    estimate: int, expected: int
) -> None:
    # Without the clamp, stating an estimate under one grid step and leaving the chunk to its
    # default would produce a T1 rejection the caller did not cause: a 422 for a field they
    # never sent.
    minimum = default_min_chunk_minutes(estimate)

    assert minimum == expected
    require_a_chunk_that_fits(estimate_minutes=estimate, min_chunk_minutes=minimum)
