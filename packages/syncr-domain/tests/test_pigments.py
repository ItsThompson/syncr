"""The sealed ramp and the deal.

The deal order is a design-language decision, so what is asserted here is the shape of it:
that it is a permutation of the ramp, that it wraps rather than inventing a thirteenth step,
and that the first four Areas take four distinct steps.

**The hue spacing those four steps give is deliberately not asserted in Python.** The inks and
their hues live in `frontend/src/tokens/primitives.css`, one of them has already been retuned, and
restating twelve hue values here would be a second source of truth for the visual language:
a spacing test written against a copy of them would go on passing after the copy went stale.
The token layer's own gate pins the spacing instead, deriving each hue from the pigment's hex.
"""

from __future__ import annotations

import pytest

from syncr_domain.pigments import (
    FIRST_FOUR_DEALT,
    PIGMENT_COUNT,
    PIGMENT_DEAL_ORDER,
    PigmentError,
    is_ramp_exhausted,
    next_pigment_index,
    require_pigment_index,
)


def test_the_ramp_is_sealed_at_twelve_steps() -> None:
    assert PIGMENT_COUNT == 12
    assert len(PIGMENT_DEAL_ORDER) == PIGMENT_COUNT


def test_the_deal_order_is_a_permutation_of_every_step() -> None:
    # A repeated step would leave one ink unreachable while two Areas collided before the
    # ramp was even full, which is the failure the deal exists to postpone.
    assert sorted(PIGMENT_DEAL_ORDER) == list(range(PIGMENT_COUNT))


def test_the_deal_order_is_the_one_the_token_layer_states() -> None:
    # Written one-based here, as `--area-01` through `--area-12` are named, so this reads
    # against `frontend/src/tokens/color.css` without arithmetic.
    assert [index + 1 for index in PIGMENT_DEAL_ORDER] == [1, 5, 8, 10, 3, 7, 12, 6, 2, 4, 9, 11]


def test_the_first_four_areas_take_four_distinct_steps() -> None:
    dealt = [next_pigment_index(count) for count in range(FIRST_FOUR_DEALT)]

    assert len(set(dealt)) == FIRST_FOUR_DEALT
    assert dealt == [0, 4, 7, 9]


def test_every_step_is_dealt_once_before_any_is_dealt_twice() -> None:
    dealt = [next_pigment_index(count) for count in range(PIGMENT_COUNT)]

    assert sorted(dealt) == list(range(PIGMENT_COUNT))


def test_the_thirteenth_area_reuses_the_first_step() -> None:
    assert next_pigment_index(PIGMENT_COUNT) == next_pigment_index(0)
    assert next_pigment_index(PIGMENT_COUNT + 1) == next_pigment_index(1)


@pytest.mark.parametrize(
    ("assigned", "exhausted"),
    [(0, False), (11, False), (12, True), (13, True), (24, True)],
    ids=["none", "one step left", "full", "past full", "twice round"],
)
def test_the_ramp_reports_exhaustion_at_the_step_it_runs_out(
    assigned: int, exhausted: bool
) -> None:
    # A control at each end of the boundary: eleven Areas still have an unused step, twelve
    # do not.
    assert is_ramp_exhausted(assigned) is exhausted


@pytest.mark.parametrize("value", [-1, PIGMENT_COUNT, PIGMENT_COUNT + 1, 100])
def test_a_value_outside_the_ramp_is_refused(value: int) -> None:
    with pytest.raises(PigmentError, match="not a step of the ramp"):
        require_pigment_index(value)


@pytest.mark.parametrize("value", [0, 1, PIGMENT_COUNT - 1])
def test_every_step_of_the_ramp_is_accepted(value: int) -> None:
    # The other half of the bound: the rejection above must distinguish rather than refuse
    # everything.
    assert require_pigment_index(value) == value


def test_a_negative_count_of_areas_is_refused() -> None:
    with pytest.raises(PigmentError, match="not a count"):
        next_pigment_index(-1)
    with pytest.raises(PigmentError, match="not a count"):
        is_ramp_exhausted(-1)
