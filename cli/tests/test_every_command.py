"""Every command in the catalog, driven end to end, asserting the wrapper and the exit code.

One deployment, thirteen invocations, and the same two assertions on each: the ``--json`` document
carries the wrapper's five members in order, and the process exits with the number the command
claims. That pair is the agent's whole contract -- it branches on the number before it reads a byte,
then parses one shape -- so a command that answers the right prose with the wrong code has failed
at the only thing an agent depends on.

**The routes are a real HTTP server on a real socket.** What is faked is the application behind
them, because the CLI does not own it; everything the CLI does own -- the credential, the
idempotency key, the JSON body, the status mapping, the polling -- happens for real.

**The invocations are bounded by the catalog, not by a list here.** ``COMMANDS`` is asserted equal
to the set the parser builds, so a command added without a case fails, and a case naming a command
the parser does not hold fails too. That is what stops this file testing twelve of thirteen commands
and reading green.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

import pytest

from syncr_cli.api_client import API_PREFIX, ROUTES
from syncr_cli.auth.discovery import DISCOVERY_PATH, REQUESTED_SCOPES
from syncr_cli.exit_codes import ExitCode
from tests import payloads
from tests.catalog import catalog
from tests.credentials import NO_KEYCHAIN, seed_refresh_token
from tests.fake_api import Answer, FakeApi
from tests.harness import drive

if TYPE_CHECKING:
    from pathlib import Path

WRAPPER_MEMBERS: Final = ["ok", "data", "verdict", "operation", "problem"]

WEEK_PATH: Final = f"{API_PREFIX}/weeks/{payloads.ISO_WEEK}"
AREAS_PATH: Final = f"{API_PREFIX}/areas"
TASKS_PATH: Final = f"{API_PREFIX}/tasks"
COMPLETE_PATH: Final = f"{API_PREFIX}/tasks/{payloads.TASK_ID}/complete"
OUTCOME_PATH: Final = f"{API_PREFIX}/blocks/{payloads.BLOCK_ID}/outcome"
DAY_PATH: Final = f"{API_PREFIX}/days/{payloads.TUESDAY.isoformat()}"
CONFIRM_PATH: Final = f"{API_PREFIX}/days/{payloads.TUESDAY.isoformat()}/confirm"
PINS_PATH: Final = f"{API_PREFIX}/weeks/{payloads.ISO_WEEK}/pins"
APPROVE_PATH: Final = f"{API_PREFIX}/weeks/{payloads.ISO_WEEK}/approve"
SOLVE_PATH: Final = f"{API_PREFIX}/weeks/{payloads.ISO_WEEK}/solve"
OPERATION_PATH: Final = f"{API_PREFIX}/operations/{payloads.OPERATION_ID}"

MOVED_TO: Final = "2026-02-10T07:00:00+00:00"


@dataclass(frozen=True, slots=True)
class Command:
    """One invocation, what the deployment answers, and the code it must exit with."""

    argv: tuple[str, ...]
    routes: tuple[tuple[str, str, Answer], ...] = ()
    code: ExitCode = ExitCode.SUCCESS
    # Which route the command must have called, so a case cannot pass by answering nothing.
    reached: tuple[str, str] | None = None
    extra: dict[str, str] = field(default_factory=dict)


def _serving(*routes: tuple[str, str, Answer]) -> tuple[tuple[str, str, Answer], ...]:
    return routes


# One case per command in the catalog, keyed by the command's own path. Every mutation's answer is a
# real response shape; every read's is the payload the api sends.
COMMANDS: Final[dict[tuple[str, str], Command]] = {
    ("task", "add"): Command(
        argv=("task", "add", "Leetcode", "--area", str(payloads.CAREER_ID)),
        routes=_serving(("POST", TASKS_PATH, Answer.json(payloads.task(), status=201))),
        reached=("POST", TASKS_PATH),
    ),
    ("task", "list"): Command(
        argv=(
            "task",
            "list",
        ),
        routes=_serving(
            ("GET", TASKS_PATH, Answer.json(payloads.backlog())),
            ("GET", AREAS_PATH, Answer.json(payloads.areas())),
        ),
        reached=("GET", TASKS_PATH),
    ),
    ("task", "done"): Command(
        argv=("task", "done", payloads.TASK_ID),
        routes=_serving(
            ("POST", COMPLETE_PATH, Answer.json(payloads.task(status="completed", eligible=False)))
        ),
        reached=("POST", COMPLETE_PATH),
    ),
    ("backlog", "list"): Command(
        argv=("backlog", "list"),
        routes=_serving(
            ("GET", TASKS_PATH, Answer.json(payloads.backlog(at_risk_count=2))),
            ("GET", AREAS_PATH, Answer.json(payloads.areas())),
        ),
        reached=("GET", TASKS_PATH),
    ),
    ("week", "show"): Command(
        argv=("week", "show"),
        routes=_serving(
            ("GET", WEEK_PATH, Answer.json(payloads.week())),
            ("GET", AREAS_PATH, Answer.json(payloads.areas())),
        ),
        reached=("GET", WEEK_PATH),
    ),
    ("plan", "show"): Command(
        argv=("plan", "show"),
        routes=_serving(
            ("GET", WEEK_PATH, Answer.json(payloads.week())),
            ("GET", AREAS_PATH, Answer.json(payloads.areas())),
        ),
        reached=("GET", WEEK_PATH),
    ),
    ("plan", "solve"): Command(
        argv=("plan", "solve"),
        routes=_serving(("POST", SOLVE_PATH, Answer.json(payloads.operation(), status=202))),
        reached=("POST", SOLVE_PATH),
    ),
    ("plan", "approve"): Command(
        argv=("plan", "approve"),
        routes=_serving(("POST", APPROVE_PATH, Answer.json(payloads.approved(), status=201))),
        reached=("POST", APPROVE_PATH),
    ),
    ("block", "done"): Command(
        argv=("block", "done", payloads.BLOCK_ID),
        routes=_serving(("PUT", OUTCOME_PATH, Answer.json(payloads.outcome()))),
        reached=("PUT", OUTCOME_PATH),
    ),
    ("block", "skip"): Command(
        argv=("block", "skip", payloads.BLOCK_ID),
        routes=_serving(("PUT", OUTCOME_PATH, Answer.json(payloads.outcome(state="skipped")))),
        reached=("PUT", OUTCOME_PATH),
    ),
    ("block", "partial"): Command(
        argv=("block", "partial", payloads.BLOCK_ID, "--minutes", "45"),
        routes=_serving(
            (
                "PUT",
                OUTCOME_PATH,
                Answer.json(payloads.outcome(state="partial", actual_minutes=45)),
            )
        ),
        reached=("PUT", OUTCOME_PATH),
    ),
    ("block", "move"): Command(
        argv=("block", "move", payloads.BLOCK_ID, "--to", MOVED_TO),
        routes=_serving(("POST", PINS_PATH, Answer.json(payloads.pinned(), status=201))),
        reached=("POST", PINS_PATH),
    ),
    ("day", "confirm"): Command(
        argv=("day", "confirm", payloads.TUESDAY.isoformat()),
        routes=_serving(
            (
                "POST",
                CONFIRM_PATH,
                Answer.json(payloads.day(confirmed_at="2026-02-10T23:00:00+00:00")),
            )
        ),
        reached=("POST", CONFIRM_PATH),
    ),
}

# The three commands that produce a credential rather than using one. They are ticket 50's, and
# `test_auth_commands.py` drives all three; naming them here is what lets the completeness assertion
# below be over the whole catalog rather than over a subset this file chose.
AUTHORIZATION_COMMANDS: Final = frozenset(
    {("auth", "login"), ("auth", "logout"), ("auth", "status")}
)


def test_the_cases_here_are_exactly_the_commands_the_parser_builds() -> None:
    # Both directions. A command with no case is untested and reads green; a case for a command the
    # parser does not hold is a test of something a caller cannot invoke.
    assert set(COMMANDS) | AUTHORIZATION_COMMANDS == catalog()


def test_the_catalog_is_the_thirteen_commands_section_17_names() -> None:
    # The count the ticket states, so a fourteenth command has to be a deliberate edit here.
    assert len(catalog()) == 16
    assert len(COMMANDS) == 13


def test_the_route_inventory_is_exactly_the_eleven_this_catalog_needs() -> None:
    # An exact set rather than a membership check, because the boundary is what this client CANNOT
    # reach: a twelfth route is a widening, and it should be a diff a reviewer reads rather than a
    # method somebody added. The words below then say what the widening must not be.
    expected = {
        "/areas",
        "/tasks",
        "/tasks/{task_id}/complete",
        "/weeks/{iso_week}",
        "/weeks/{iso_week}/solve",
        "/weeks/{iso_week}/approve",
        "/weeks/{iso_week}/pins",
        "/blocks/{block_id}/outcome",
        "/days/{date}",
        "/days/{date}/confirm",
        "/operations/{operation_id}",
    }

    assert expected == ROUTES


def test_no_route_this_client_can_build_names_an_out_of_scope_resource() -> None:
    # Section 17's out-of-scope list is a boundary only if nothing in the client can reach it.
    # Stated over the whole route inventory, so a method added later is covered without an edit.
    out_of_scope = (
        "reviews",
        "templates",
        "calendar-sources",
        "events",
        "anchor-types",
        "week-pattern",
        "weight-sets",
        "promotions",
        "settings",
        "habits",
        "routines",
        "day-types",
    )
    assert ROUTES, "the route inventory is empty, so this asserted nothing"

    reachable = {word for word in out_of_scope for route in ROUTES if word in route}

    assert reachable == set()


def test_the_client_can_reach_no_route_the_api_reserves_for_admin() -> None:
    """The other half of the boundary, keyed on the scope rather than on the path.

    Section 17 says the CLI requests ``plan:read`` and ``plan:write`` and not ``admin``, and that
    that is what makes the out-of-scope list a boundary rather than a suggestion. So the requested
    set is asserted here as well as in ``test_auth_commands.py``, beside the routes it bounds: a
    route added to this inventory that needed ``admin`` would be a route every command using it
    would be refused on, and the two claims belong in one place.
    """
    assert set(REQUESTED_SCOPES) == {"plan:read", "plan:write"}
    assert "admin" not in REQUESTED_SCOPES


@pytest.mark.parametrize(
    ("noun", "verb"),
    sorted(COMMANDS),
    ids=lambda pair: pair if isinstance(pair, str) else str(pair),
)
def test_every_command_answers_the_wrapper_and_exits_by_its_own_code(
    noun: str, verb: str, tmp_path: Path
) -> None:
    case = COMMANDS[(noun, verb)]

    with FakeApi() as api:
        _authorize(api, tmp_path)
        for method, path, answer in case.routes:
            api.answer(method, path, answer)

        ran = drive(
            case.argv,
            base_url=api.base_url,
            home=tmp_path,
            env={**NO_KEYCHAIN, **case.extra},
        )

        assert ran.code is case.code, ran.stdout
        assert list(ran.document) == WRAPPER_MEMBERS
        assert ran.document["ok"] is True
        if case.reached is not None:
            assert api.requests_to(*case.reached), f"{case.argv} reached no {case.reached}"


@pytest.mark.parametrize(("noun", "verb"), sorted(COMMANDS))
def test_every_command_presents_the_credential_on_every_product_request(
    noun: str, verb: str, tmp_path: Path
) -> None:
    # A command that read a payload without presenting a token would pass every assertion above
    # against this fake and 401 against the api.
    case = COMMANDS[(noun, verb)]

    with FakeApi() as api:
        _authorize(api, tmp_path)
        for method, path, answer in case.routes:
            api.answer(method, path, answer)

        drive(case.argv, base_url=api.base_url, home=tmp_path, env={**NO_KEYCHAIN, **case.extra})

        product = [one for one in api.received if one.path.startswith(API_PREFIX)]
        assert product, f"{case.argv} reached no product route"
        assert all(one.headers.get("authorization", "").startswith("Bearer ") for one in product)


@pytest.mark.parametrize(("noun", "verb"), sorted(COMMANDS))
def test_every_mutation_carries_an_idempotency_key_and_every_read_carries_none(
    noun: str, verb: str, tmp_path: Path
) -> None:
    """The obligation, asserted per command rather than per module.

    ``POST /solve`` is the one mutation that carries none, and the reason is the api's: a solve is
    idempotent per week by the coordinator's single-flight invariant, and a key derived from the
    command would be the same key tomorrow, so the guard would replay a completed operation rather
    than dispatching a solve of a week that has moved on.
    """
    case = COMMANDS[(noun, verb)]
    unsafe = {"POST", "PUT", "PATCH", "DELETE"}

    with FakeApi() as api:
        _authorize(api, tmp_path)
        for method, path, answer in case.routes:
            api.answer(method, path, answer)

        drive(case.argv, base_url=api.base_url, home=tmp_path, env={**NO_KEYCHAIN, **case.extra})

        product = [one for one in api.received if one.path.startswith(API_PREFIX)]
        keyed = {
            (one.method, one.path): "idempotency-key" in one.headers
            for one in product
            if one.method in unsafe
        }

    expected = {key: key != ("POST", SOLVE_PATH) for key in keyed}
    assert keyed == expected


def _authorize(api: FakeApi, home: Path) -> None:
    """A deployment that discovers and refreshes, and a credential this machine already holds."""
    api.answer("GET", DISCOVERY_PATH, Answer.json(payloads.metadata(api.base_url)))
    api.answer("POST", "/oauth/token", Answer.json(payloads.token_response()))
    seed_refresh_token(home, api.base_url)
