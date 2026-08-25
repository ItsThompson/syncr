"""The routine wire contract's wall-time rule, asserted without a server.

The routes suite drives the same refusals through HTTP and a real row, which is where the 422's
shape and the untouched row are asserted. What needs saying without either is that this boundary
does not hold its own copy of the rule: it asks the domain which half of it a value breaks, and it
keeps its own two messages because a caller reading a 422 is told about a request field rather than
about an entity.

The substitution below is what makes that checkable. A boundary that tested the value itself would
go on accepting what the substituted statement refuses, and no assertion over messages could tell
the two apart.
"""

from __future__ import annotations

from datetime import time

import pytest
from pydantic import ValidationError

from syncr_api.routines import schemas
from syncr_api.routines.schemas import RoutineCreateRequest, RoutinePatchRequest
from syncr_domain.snap import NotAWallTime

SLEEP = {
    "title": "Sleep",
    "targetTime": "23:00",
    "durationMinutes": 480,
    "minDurationMinutes": 480,
    "flexBandMinutes": 0,
}

# A whole minute off the quarter hour. This boundary holds only the wall-time rule: the grid is
# the span's to refuse, so this is the value that separates "not a wall time" from "not on the
# grid" at this boundary.
OFF_THE_QUARTER_HOUR = "23:07"


def a_statement_refusing_everything(value: object) -> NotAWallTime:
    """A substitute for the domain's statement that refuses what the real one accepts."""
    assert value is not None
    return NotAWallTime.CARRIES_A_ZONE


@pytest.mark.parametrize(
    "offered",
    ["23:00:00+01:00", "23:00:00Z", "23:00:30", "23:00:00.500000"],
    ids=["an offset", "a UTC marker", "a second", "a microsecond"],
)
def test_a_target_time_that_is_not_wall_time_is_refused_on_both_verbs(offered: str) -> None:
    with pytest.raises(ValidationError) as on_create:
        RoutineCreateRequest.model_validate({**SLEEP, "targetTime": offered})

    with pytest.raises(ValidationError) as on_patch:
        RoutinePatchRequest.model_validate({"targetTime": offered})

    assert [error["loc"] for error in on_create.value.errors()] == [("targetTime",)]
    assert [error["loc"] for error in on_patch.value.errors()] == [("targetTime",)]


@pytest.mark.parametrize(
    "offered", ["23:00", OFF_THE_QUARTER_HOUR], ids=["a quarter hour", "off the quarter hour"]
)
def test_a_wall_time_on_any_whole_minute_is_accepted(offered: str) -> None:
    declared = RoutineCreateRequest.model_validate({**SLEEP, "targetTime": offered})

    assert declared.target_time == time.fromisoformat(offered)


def test_the_boundary_asks_the_domain_which_half_of_the_rule_a_value_breaks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The control first: this value is accepted today, so the refusal below can only come from
    # the substitution.
    assert RoutineCreateRequest.model_validate(SLEEP).target_time == time(23, 0)

    monkeypatch.setattr(schemas, "not_a_wall_time", a_statement_refusing_everything)

    with pytest.raises(ValidationError) as refused:
        RoutineCreateRequest.model_validate(SLEEP)

    assert [error["loc"] for error in refused.value.errors()] == [("targetTime",)]
