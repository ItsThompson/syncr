"""Reading problem details, and the number each one exits with.

Two properties matter more than the individual rows. A type this build has never seen must still
produce a sensible code, because the api may name a condition that postdates the binary; and a
body that is not problem details at all must not fault, because a proxy that never reached the
application answers HTML.
"""

from __future__ import annotations

import json
from typing import Final

import pytest

from syncr_cli.exit_codes import ExitCode
from syncr_cli.problems import (
    EXIT_CODE_BY_PROBLEM_TYPE,
    NO_STATUS,
    cli_problem,
    exit_code_for_status,
    read_problem,
)

# What each condition exits with, written from the documented table rather than read from the one
# under test. A parametrization over `EXIT_CODE_BY_PROBLEM_TYPE` would be the mapping asserting
# itself: it passes for any mapping at all, including a wrong one. Stated here, a change to the
# code has to be a deliberate change to a test named after the rule as well.
DOCUMENTED: Final[dict[str, ExitCode]] = {
    "syncr:malformed-request": ExitCode.USAGE,
    "syncr:unauthorized": ExitCode.NOT_AUTHENTICATED,
    "syncr:forbidden": ExitCode.INSUFFICIENT_SCOPE,
    "syncr:origin-rejected": ExitCode.FAILURE,
    "syncr:not-found": ExitCode.NOT_FOUND,
    "syncr:conflict": ExitCode.CONFLICT,
    "syncr:idempotency-request-in-flight": ExitCode.CONFLICT,
    "syncr:validation-failed": ExitCode.VALIDATION_FAILED,
    "syncr:rate-limited": ExitCode.API_UNAVAILABLE,
    "syncr:dependency-unavailable": ExitCode.API_UNAVAILABLE,
    "syncr:internal-error": ExitCode.FAILURE,
    "syncr:oauth-invalid-request": ExitCode.USAGE,
    "syncr:oauth-invalid-grant": ExitCode.NOT_AUTHENTICATED,
    "syncr:oauth-invalid-token": ExitCode.NOT_AUTHENTICATED,
    "syncr:oauth-invalid-client": ExitCode.FAILURE,
    "syncr:oauth-unsupported-grant-type": ExitCode.FAILURE,
    "syncr:cli-usage": ExitCode.USAGE,
    "syncr:cli-not-authenticated": ExitCode.NOT_AUTHENTICATED,
    "syncr:cli-api-unreachable": ExitCode.API_UNAVAILABLE,
    "syncr:cli-timed-out": ExitCode.TIMED_OUT,
    "syncr:cli-failure": ExitCode.FAILURE,
    "syncr:cli-malformed-response": ExitCode.FAILURE,
}


def test_the_documented_types_are_exactly_the_types_the_table_maps() -> None:
    # The other direction: a type added to the code with no documented expectation, or an
    # expectation for a type the code no longer maps.
    assert set(DOCUMENTED) == set(EXIT_CODE_BY_PROBLEM_TYPE)


@pytest.mark.parametrize(("problem_type", "expected"), sorted(DOCUMENTED.items()))
def test_each_known_problem_type_exits_with_its_own_code(
    problem_type: str, expected: ExitCode
) -> None:
    problem = read_problem(400, _body(problem_type, status=400))

    assert problem.exit_code is expected


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, ExitCode.USAGE),
        (401, ExitCode.NOT_AUTHENTICATED),
        (403, ExitCode.INSUFFICIENT_SCOPE),
        (404, ExitCode.NOT_FOUND),
        (409, ExitCode.CONFLICT),
        (422, ExitCode.VALIDATION_FAILED),
        (429, ExitCode.API_UNAVAILABLE),
        (500, ExitCode.FAILURE),
        (502, ExitCode.API_UNAVAILABLE),
        (503, ExitCode.API_UNAVAILABLE),
        (504, ExitCode.API_UNAVAILABLE),
    ],
)
def test_a_type_this_build_has_never_seen_exits_by_its_status(
    status: int, expected: ExitCode
) -> None:
    problem = read_problem(status, _body("syncr:a-condition-from-a-later-api", status=status))

    assert problem.exit_code is expected


def test_a_status_with_no_rule_is_a_generic_failure() -> None:
    assert exit_code_for_status(418) is ExitCode.FAILURE


def test_a_body_that_is_not_json_is_reported_as_the_body_it_turned_out_to_be() -> None:
    problem = read_problem(502, b"<html><body>Bad gateway</body></html>")

    assert problem.status == 502
    assert problem.exit_code is ExitCode.API_UNAVAILABLE
    assert "Bad gateway" in problem.detail


def test_an_empty_body_says_so_rather_than_rendering_nothing() -> None:
    problem = read_problem(500, b"")

    assert "empty body" in problem.detail
    assert problem.exit_code is ExitCode.FAILURE


def test_a_long_body_is_shortened_rather_than_becoming_the_output() -> None:
    problem = read_problem(500, b"x" * 5_000)

    assert problem.detail.endswith("...")
    assert len(problem.detail) < 300


def test_a_partial_problem_keeps_the_status_the_response_carried() -> None:
    # A body with a type and nothing else is still a problem, and the status is the exchange's.
    problem = read_problem(409, json.dumps({"type": "syncr:conflict"}).encode("utf-8"))

    assert problem.status == 409
    assert problem.title == "HTTP 409"
    assert problem.exit_code is ExitCode.CONFLICT


def test_a_status_member_that_is_not_a_number_does_not_displace_the_real_one() -> None:
    body = json.dumps({"type": "syncr:conflict", "status": True}).encode("utf-8")

    assert read_problem(409, body).status == 409


def test_field_level_failures_are_read_and_malformed_entries_are_not() -> None:
    body = json.dumps(
        {
            "type": "syncr:validation-failed",
            "title": "Validation failed",
            "status": 422,
            "detail": "Two fields are wrong. Nothing was changed.",
            "errors": [
                {"field": "minimumChunkMinutes", "message": "above the estimate"},
                "not an object",
            ],
        }
    ).encode("utf-8")

    problem = read_problem(422, body)

    assert [(one.field, one.message) for one in problem.errors] == [
        ("minimumChunkMinutes", "above the estimate")
    ]


def test_a_problem_the_cli_mints_claims_no_http_status() -> None:
    problem = cli_problem("syncr:cli-usage", "Usage error", "no such flag")

    assert problem.status == NO_STATUS
    assert problem.exit_code is ExitCode.USAGE


def _body(problem_type: str, *, status: int) -> bytes:
    return json.dumps(
        {
            "type": problem_type,
            "title": "Refused",
            "status": status,
            "detail": "Nothing was changed.",
        }
    ).encode("utf-8")
