"""The settings wire contract's wall-time rule, asserted without a server.

The routes suite drives the same refusals through HTTP and a real row, which is where the 422's
shape and the untouched row are asserted. What needs saying without either is that this boundary
does not hold its own copy of the rule: it asks the domain which half of it a value breaks, and it
keeps its own two messages because a caller reading a 422 is told about a day bound rather than
about a routine's target time.

The substitution below is what makes that checkable. A boundary that tested the value itself would
go on accepting what the substituted statement refuses, and no assertion over messages could tell
the two apart.
"""

from __future__ import annotations

from datetime import time
from typing import Final

import pytest
from pydantic import ValidationError

from syncr_api.user_settings import schemas
from syncr_api.user_settings.schemas import SettingsPatchRequest
from syncr_domain.snap import NotAWallTime

# Both bounds, as the wire spells each one and as the model holds it. Every test below runs over
# both, because the two behave identically and a rule reaching one of them is the failure that
# would leave the other silent.
BOUNDS: Final = {"dayStart": "day_start", "dayEnd": "day_end"}

# A whole minute off the quarter hour. The day bounds draw the grid's own axis and materialize no
# block, so this is the value that separates "not a wall time" from "not on the snap grid" here.
OFF_THE_QUARTER_HOUR = "07:07"

NOT_WALL_TIME = ["07:00:00+05:00", "07:00:00Z", "07:00:30", "07:00:00.500000"]
NOT_WALL_TIME_IDS = ["an offset", "a UTC marker", "a second", "a microsecond"]


def a_statement_refusing_everything(value: object) -> NotAWallTime:
    """A substitute for the domain's statement that refuses what the real one accepts."""
    assert value is not None
    return NotAWallTime.CARRIES_A_ZONE


@pytest.mark.parametrize("bound", BOUNDS)
@pytest.mark.parametrize("offered", NOT_WALL_TIME, ids=NOT_WALL_TIME_IDS)
def test_a_day_bound_that_is_not_wall_time_is_refused_on_its_own_field(
    bound: str, offered: str
) -> None:
    with pytest.raises(ValidationError) as refused:
        SettingsPatchRequest.model_validate({bound: offered})

    assert [error["loc"] for error in refused.value.errors()] == [(bound,)]


@pytest.mark.parametrize("offered", NOT_WALL_TIME, ids=NOT_WALL_TIME_IDS)
def test_a_body_naming_both_bounds_is_refused_on_both(offered: str) -> None:
    # A rule applied to one field, or to whichever field pydantic reached first, would answer a
    # single error here and leave the caller to discover the second bound on the next request.
    with pytest.raises(ValidationError) as refused:
        SettingsPatchRequest.model_validate({"dayStart": offered, "dayEnd": offered})

    assert [error["loc"] for error in refused.value.errors()] == [("dayStart",), ("dayEnd",)]


@pytest.mark.parametrize("bound", BOUNDS)
def test_the_refusal_says_which_half_of_the_rule_the_value_breaks(bound: str) -> None:
    # The two halves are distinguishable to a reader, so a form can say what to send instead
    # rather than only that the value was wrong.
    with pytest.raises(ValidationError) as zoned:
        SettingsPatchRequest.model_validate({bound: "07:00:00+05:00"})
    with pytest.raises(ValidationError) as sub_minute:
        SettingsPatchRequest.model_validate({bound: "07:00:30"})

    assert "an offset is refused" in zoned.value.errors()[0]["msg"]
    assert "seconds are refused" in sub_minute.value.errors()[0]["msg"]


@pytest.mark.parametrize(("bound", "attribute"), BOUNDS.items())
@pytest.mark.parametrize(
    "offered",
    ["07:00", "07:00:00", OFF_THE_QUARTER_HOUR],
    ids=["a quarter hour", "the form a read returns", "off the quarter hour"],
)
def test_a_wall_time_on_any_whole_minute_is_accepted(
    bound: str, attribute: str, offered: str
) -> None:
    # Two of these carry the rule. Off the quarter hour says the day bounds take the wall-time
    # rule without the snap, so a bound a placement could not hold is still a bound. `07:00:00` is
    # the form a read renders, so read-modify-write does not have to normalize what it was given.
    declared = SettingsPatchRequest.model_validate({bound: offered})

    assert getattr(declared, attribute) == time.fromisoformat(offered)


@pytest.mark.parametrize(("bound", "attribute"), BOUNDS.items())
def test_the_boundary_asks_the_domain_which_half_of_the_rule_a_value_breaks(
    bound: str, attribute: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The control first: this value is accepted today, so the refusal below can only come from
    # the substitution.
    accepted = SettingsPatchRequest.model_validate({bound: "07:00"})
    assert getattr(accepted, attribute) == time(7, 0)

    monkeypatch.setattr(schemas, "not_a_wall_time", a_statement_refusing_everything)

    with pytest.raises(ValidationError) as refused:
        SettingsPatchRequest.model_validate({bound: "07:00"})

    assert [error["loc"] for error in refused.value.errors()] == [(bound,)]
