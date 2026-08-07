"""Every documented exit code, observed from a real process.

**A table asserting a table proves nothing.** So each case here makes the condition happen against a
real server and reads the number a real process exited with. ``python -m syncr_cli`` is what is run,
which is the entry point the ``syncr`` console script calls, not a function in this interpreter, so
what is asserted is what a shell and an agent see.

The case table is bounded by ``ExitCode`` itself: a member with no case fails a test, which is what
stops the documented table from rotting as the code grows.

**Every code is reached through the script now, and the exemption set is empty.** Ticket 50 could
not provoke 9 or 10 from a command, because no command in that slice dispatched long-running work,
so both were reached in its own interpreter and the gap was pinned rather than hidden.
``plan solve --wait`` dispatches work, so a supersession and a timeout are both a real process
exiting with a real number.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import syncr_cli
from syncr_cli.auth.discovery import DISCOVERY_PATH
from syncr_cli.exit_codes import ExitCode
from tests import payloads
from tests.child import child_environment
from tests.credentials import NO_KEYCHAIN, seed_refresh_token
from tests.fake_api import Answer, FakeApi

if TYPE_CHECKING:
    from collections.abc import Callable

WEEK_PATH = f"/api/v1/weeks/{payloads.ISO_WEEK}"
AREAS_PATH = "/api/v1/areas"
OPERATION_PATH = f"/api/v1/operations/{payloads.OPERATION_ID}"
SOLVE_PATH = f"/api/v1/weeks/{payloads.ISO_WEEK}/solve"
STORED_REFRESH = "syncrr_stored"  # pragma: allowlist secret

# The subprocess resolves `keyring`'s backend the way a headless machine does, through keyring's own
# variable, so the credential lands in the 0600 file rather than in this developer's keychain. Owned
# by `tests/credentials.py` because three files need the same answer.


@dataclass(frozen=True, slots=True)
class Case:
    """One condition, the arguments that provoke it, and whether the wrapper reports success."""

    argv: tuple[str, ...]
    routes: Callable[[FakeApi], None]
    authorized: bool = True
    # Whether `ok` is true when this code is reached. False for every failure, and true for the two
    # normal outcomes that are not success: an infeasible week is the product working correctly, and
    # a superseded solve is the expected result of editing quickly, so neither carries a problem.
    ok: bool = False


def _serving(
    *, week: Answer | None = None, areas: Answer | None = None
) -> Callable[[FakeApi], None]:
    """A deployment that discovers, refreshes, and answers both of ``week show``'s reads."""

    def routes(api: FakeApi) -> None:
        api.answer("GET", DISCOVERY_PATH, Answer.json(payloads.metadata(api.base_url)))
        api.answer("POST", "/oauth/token", Answer.json(payloads.token_response()))
        api.answer("GET", AREAS_PATH, areas or Answer.json(payloads.areas()))
        api.answer("GET", WEEK_PATH, week or Answer.json(payloads.week()))

    return routes


def _refusal(problem_type: str, status: int) -> Answer:
    return Answer.problem(payloads.problem(problem_type=problem_type, status=status), status=status)


def _waiting(*operations: Answer) -> Callable[[FakeApi], None]:
    """A deployment that accepts a solve and answers the poll with ``operations`` in turn."""

    def routes(api: FakeApi) -> None:
        _serving()(api)
        api.answer("POST", SOLVE_PATH, Answer.json(payloads.operation(), status=202))
        api.answer_in_turn("GET", OPERATION_PATH, *operations)

    return routes


# The arguments that make a wait end at the timeout rather than at a status, in one real second: the
# poll interval and the timeout are the smallest the settings allow, so the child process does not
# hold the suite for a minute.
A_WAIT_THAT_RUNS_OUT = ("plan", "solve", "--wait", "--timeout", "1", "--poll-interval", "1")

CASES: dict[ExitCode, Case] = {
    ExitCode.SUCCESS: Case(argv=("week", "show"), routes=_serving(), ok=True),
    ExitCode.FAILURE: Case(
        argv=("week", "show"), routes=_serving(week=_refusal("syncr:internal-error", 500))
    ),
    ExitCode.USAGE: Case(argv=("week", "show", "--no-such-flag"), routes=_serving()),
    ExitCode.NOT_AUTHENTICATED: Case(argv=("week", "show"), routes=_serving(), authorized=False),
    ExitCode.INSUFFICIENT_SCOPE: Case(
        argv=("week", "show"), routes=_serving(week=_refusal("syncr:forbidden", 403))
    ),
    ExitCode.NOT_FOUND: Case(
        argv=("week", "show"), routes=_serving(week=_refusal("syncr:not-found", 404))
    ),
    ExitCode.CONFLICT: Case(
        argv=("week", "show"), routes=_serving(week=_refusal("syncr:conflict", 409))
    ),
    ExitCode.VALIDATION_FAILED: Case(
        argv=("week", "show"), routes=_serving(week=_refusal("syncr:validation-failed", 422))
    ),
    ExitCode.INFEASIBLE: Case(
        argv=("week", "show"),
        routes=_serving(week=Answer.json(payloads.week(week_verdict=payloads.verdict()))),
        ok=True,
    ),
    ExitCode.SUPERSEDED: Case(
        argv=("plan", "solve", "--wait"),
        routes=_waiting(
            Answer.json(
                payloads.operation(status="superseded", superseded_by=payloads.SUCCESSOR_ID)
            )
        ),
        ok=True,
    ),
    ExitCode.TIMED_OUT: Case(
        argv=A_WAIT_THAT_RUNS_OUT,
        routes=_waiting(Answer.json(payloads.operation(status="running"))),
    ),
    ExitCode.API_UNAVAILABLE: Case(
        argv=("week", "show"), routes=_serving(week=_refusal("syncr:dependency-unavailable", 503))
    ),
}


def test_every_documented_exit_code_has_a_case() -> None:
    # The guard that stops the table rotting: a new code with nothing that provokes it fails here
    # rather than being documented and unreachable.
    assert set(CASES) == set(ExitCode)


def test_every_case_runs_the_console_script_rather_than_this_interpreter() -> None:
    """What ticket 50 could not say, asserted over this module's own source.

    Two codes were reached in ticket 50's own interpreter because no command dispatched work.
    ``plan solve --wait`` does, so the exemption set is gone, and this is what stops one coming
    back: an in-interpreter case would have to reach the wait loop or build a result directly, the
    way the two tests it replaced did. So the guard is that no name in this file does.

    Read from the AST rather than by searching the text, because the text includes this sentence: a
    substring guard matches the names it is written to forbid and fails on its own prose. Names
    only, so a comment and a docstring are invisible to it.
    """
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    referenced = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    # The precondition: the one runner really is a subprocess of the entry point, and it is the only
    # one. Asserted on the call rather than on a string, so a second runner is visible.
    runners = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "run"
    ]
    assert len(runners) == 2, "expected exactly `subprocess.run` in `_run` and in the source probe"

    # And nothing here reaches the shapes an in-interpreter case needs: `wait_for_operation` is the
    # loop, and `CliResult` is what a test would build to read an exit code without exiting.
    in_the_interpreter = sorted(referenced & {"wait_for_operation", "CliResult", "Operation"})

    assert in_the_interpreter == []


@pytest.mark.parametrize("expected", list(CASES), ids=lambda code: f"{int(code)}-{code.name}")
def test_the_process_exits_with_the_documented_code(expected: ExitCode, tmp_path: Path) -> None:
    case = CASES[expected]

    with FakeApi() as api:
        case.routes(api)
        if case.authorized:
            _seed_credential(tmp_path, api.base_url)
        completed = _run(case.argv, api.base_url, tmp_path)

    assert completed.returncode == int(expected), completed.stderr
    document = json.loads(completed.stdout)
    assert list(document) == ["ok", "data", "verdict", "operation", "problem"]
    assert document["ok"] is case.ok


def test_the_child_process_runs_the_tree_this_test_imported(tmp_path: Path) -> None:
    # The instrument's own precondition, asserted by asking the child where it imported from. A
    # subprocess that resolved the package through the interpreter's editable install would measure
    # another checkout, and every case in this file would pass for the wrong reason.
    resolved = subprocess.run(
        [
            sys.executable,
            "-c",
            "import pathlib, syncr_cli; print(pathlib.Path(syncr_cli.__file__).resolve())",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=_child_environment("http://127.0.0.1:1", tmp_path),
    )

    assert resolved.returncode == 0, resolved.stderr
    assert Path(resolved.stdout.strip()) == Path(syncr_cli.__file__).resolve()


def test_a_closed_port_also_exits_eleven(tmp_path: Path) -> None:
    # The other way the API is unavailable, and the one a wrong `api_url` produces.
    with FakeApi() as api:
        closed = api.base_url

    completed = _run(("week", "show"), closed, tmp_path)

    assert completed.returncode == int(ExitCode.API_UNAVAILABLE)


def test_a_wait_that_runs_out_exits_ten_through_the_script(tmp_path: Path) -> None:
    # Redundant with the parametrized case above by design: this asserts the two things the case
    # does not, which are that the wrapper reports the failure and that the operation travels on it
    # so the wait is resumable without parsing prose.
    with FakeApi() as api:
        _waiting(Answer.json(payloads.operation(status="running")))(api)
        _seed_credential(tmp_path, api.base_url)
        completed = _run(A_WAIT_THAT_RUNS_OUT, api.base_url, tmp_path)

    assert completed.returncode == int(ExitCode.TIMED_OUT), completed.stderr
    document = json.loads(completed.stdout)
    assert document["ok"] is False
    assert document["operation"]["id"] == payloads.OPERATION_ID
    assert payloads.OPERATION_ID in document["problem"]["detail"]


def test_a_superseded_wait_exits_nine_and_names_its_successor(tmp_path: Path) -> None:
    # Nine is only useful if it comes with the successor: an agent follows the chain rather than
    # dispatching another solve onto it. Driven through the script, and the code comes off the same
    # result the runner exits by.
    with FakeApi() as api:
        _waiting(
            Answer.json(
                payloads.operation(status="superseded", superseded_by=payloads.SUCCESSOR_ID)
            )
        )(api)
        _seed_credential(tmp_path, api.base_url)
        completed = _run(("plan", "solve", "--wait"), api.base_url, tmp_path)

    assert completed.returncode == int(ExitCode.SUPERSEDED), completed.stderr
    document = json.loads(completed.stdout)
    assert document["ok"] is True
    assert document["operation"]["supersededBy"] == payloads.SUCCESSOR_ID


def test_an_operation_a_read_only_saw_does_not_decide_that_reads_exit_code(
    tmp_path: Path,
) -> None:
    # The other half of the same rule, driven through the process: a week carrying a failed
    # operation is still a successful read, and the operation is still reported.
    failed = payloads.week(
        week_operation=payloads.operation(
            status="failed", error={"code": "solver_fault", "message": "the solver raised"}
        )
    )
    with FakeApi() as api:
        _serving(week=Answer.json(failed))(api)
        _seed_credential(tmp_path, api.base_url)
        completed = _run(("week", "show"), api.base_url, tmp_path)

    assert completed.returncode == int(ExitCode.SUCCESS), completed.stderr
    document = json.loads(completed.stdout)
    assert document["ok"] is True
    assert document["operation"]["status"] == "failed"


def _seed_credential(home: Path, api_url: str) -> None:
    """Put a refresh token where a machine with no keychain keeps one."""
    seed_refresh_token(home, api_url, token=STORED_REFRESH)


def _child_environment(api_url: str, home: Path) -> dict[str, str]:
    """The environment every child of this file runs in.

    ``tests/child.py`` owns pointing a child at the tree this suite imported, which is what stops a
    case reading green while measuring another checkout. Stated here are the values this file's
    children need on top of that, and one function rather than a literal per call site so the
    precondition test and the cases it guards cannot be given different environments.
    """
    return child_environment(
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        SYNCR_API_URL=api_url,
        # The week is stated rather than left to the machine's clock: the routes this test serves
        # are for one week, and a subprocess reads the real date.
        SYNCR_WEEK=payloads.ISO_WEEK,
        **NO_KEYCHAIN,
    )


def _run(argv: tuple[str, ...], api_url: str, home: Path) -> subprocess.CompletedProcess[str]:
    """Run the CLI's entry point itself, in an environment that reaches nothing on this machine."""
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-m", "syncr_cli", *argv],
        capture_output=True,
        text=True,
        check=False,
        env=_child_environment(api_url, home),
    )
