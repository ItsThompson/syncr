"""Absent and null, kept apart. The two readings, and the controls that distinguish them.

A partial update over a nullable field has three cases and a schema field defaulting to
``None`` collapses two of them, so what these tests pin is that the collapse does not happen:
a request that omits a floor and a request that sends ``floorHours: null`` reach the service as
different values, and one of them clears the stored floor.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from syncr_api.core.patches import ABSENT, Absent, resolved, stated, stated_unless_null


class Body(BaseModel):
    """Stands in for a patch request: two optional fields, neither required."""

    floor: int | None = None
    name: str | None = None


def test_a_field_the_request_named_is_stated() -> None:
    body = Body.model_validate({"floor": 4})

    assert stated(body, "floor", body.floor) == 4


def test_a_field_the_request_omitted_is_absent() -> None:
    body = Body.model_validate({"name": "Fitness"})

    assert stated(body, "floor", body.floor) is ABSENT


def test_an_explicit_null_is_stated_rather_than_read_as_absent() -> None:
    # The whole point. Without this distinction, clearing a floor would be unreachable.
    body = Body.model_validate({"floor": None})

    assert stated(body, "floor", body.floor) is None
    assert stated(body, "floor", body.floor) is not ABSENT


def test_a_non_nullable_field_reads_null_as_absence() -> None:
    # For a field whose schema refuses an explicit null, `None` can only mean the request left
    # it out, so the body does not have to be consulted.
    assert stated_unless_null(None) is ABSENT
    assert stated_unless_null("Fitness") == "Fitness"


@pytest.mark.parametrize(
    ("patched", "current", "expected"),
    [
        (ABSENT, 4, 4),
        (6, 4, 6),
        (None, 4, None),
        (ABSENT, None, None),
    ],
    ids=["absent keeps", "a value replaces", "null clears", "absent keeps a null"],
)
def test_resolving_a_patched_value(patched: object, current: object, expected: object) -> None:
    assert resolved(patched, current) == expected


def test_the_absent_marker_is_one_value_of_its_own_type() -> None:
    # A closed union of two cases needs the marker to be a type rather than a sentinel object,
    # so `resolved` can narrow on it and mypy can check every caller.
    assert isinstance(ABSENT, Absent)
    assert list(Absent) == [ABSENT]
