"""Every documented exit code, observed from a real process.

**A table asserting a table proves nothing.** So each case here makes the condition happen against a
real server and reads the number a real process exited with. ``python -m syncr_cli`` is what is run,
which is the entry point the ``syncr`` console script calls, not a function in this interpreter, so
what is asserted is what a shell and an agent see.

The case table is bounded by ``ExitCode`` itself: a member with no case fails a test, which is what
stops the documented table from rotting as the code grows.

Two codes are reached in this interpreter rather than through the script, and the reason is stated
where each is: no command in this slice dispatches long-running work, and an operation a read merely
saw does not decide that read's exit code. Both still run the real loop against a real server.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest

import syncr_cli
from syncr_cli.api_client import ApiClient
from syncr_cli.auth.discovery import DISCOVERY_PATH
from syncr_cli.auth.storage import CREDENTIALS_FILE_NAME
from syncr_cli.errors import WaitTimedOut
from syncr_cli.exit_codes import ExitCode
from syncr_cli.http import Transport
from syncr_cli.operations import wait_for_operation
from syncr_cli.results import CliResult
from syncr_cli.wire.operation import Operation
from tests import payloads
from tests.child import child_environment
from tests.fake_api import Answer, FakeApi

if TYPE_CHECKING:
    from collections.abc import Callable

WEEK_PATH = f"/api/v1/weeks/{payloads.ISO_WEEK}"
AREAS_PATH = "/api/v1/areas"
OPERATION_PATH = f"/api/v1/operations/{payloads.OPERATION_ID}"
STORED_REFRESH = "syncrr_stored"  # pragma: allowlist secret

# `keyring` resolves a process-global backend, and the subprocess is a different process: its
# backend is chosen the way a headless machine chooses one, through keyring's own variable. So the
# credential lands in the 0600 file, which is also what lets this test seed one.
NO_KEYCHAIN = {"PYTHON_KEYRING_BACKEND": "keyring.backends.fail.Keyring"}


@dataclass(frozen=True, slots=True)
class Case:
    """One condition, and the arguments that provoke it."""

    argv: tuple[str, ...]
    routes: Callable[[FakeApi], None]
    authorized: bool = True


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


CASES: dict[ExitCode, Case] = {
    ExitCode.SUCCESS: Case(argv=("week", "show"), routes=_serving()),
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
    ),
    ExitCode.API_UNAVAILABLE: Case(
        argv=("week", "show"), routes=_serving(week=_refusal("syncr:dependency-unavailable", 503))
    ),
}

# Reached in this interpreter, because both need a command that dispatches long-running work and
# this slice ships none. An operation a read merely saw does not decide that read's exit code -- a
# successful read must not report the status of work nobody asked for -- so neither code can be
# provoked through a shipped command. The loop, the server, and the codes are the real ones.
CODES_REACHED_WITHOUT_THE_SCRIPT = frozenset({ExitCode.SUPERSEDED, ExitCode.TIMED_OUT})


def test_the_exemption_set_is_the_two_codes_it_is_allowed_to_hold() -> None:
    # Pinned, because the cheapest way to satisfy the completeness assertion below is to exempt a
    # code rather than provoke it. Growing this set has to be a deliberate edit a reviewer sees, and
    # `plan solve --wait` empties it.
    allowed = frozenset({ExitCode.SUPERSEDED, ExitCode.TIMED_OUT})

    assert allowed == CODES_REACHED_WITHOUT_THE_SCRIPT


def test_every_documented_exit_code_has_a_case() -> None:
    # The guard that stops the table rotting: a new code with nothing that provokes it fails here
    # rather than being documented and unreachable.
    assert set(CASES) | CODES_REACHED_WITHOUT_THE_SCRIPT == set(ExitCode)


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


def test_a_wait_that_runs_out_exits_ten(tmp_path: Path) -> None:
    # Ten is reached through the wait rather than through the script: no command in this slice
    # dispatches work. The poll, the server, and the error are the real ones, and the code comes off
    # the same problem table every other failure uses.
    class _NoCredential:
        def headers(self) -> dict[str, str]:
            return {}

    now = [0.0]

    def monotonic() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    with FakeApi() as api, httpx.Client(timeout=5.0) as client:
        api.answer("GET", OPERATION_PATH, Answer.json(payloads.operation(status="running")))
        client_under_test = ApiClient(
            transport=Transport(client),
            api_url=api.base_url,
            session=_NoCredential(),
        )

        with pytest.raises(WaitTimedOut) as timed_out:
            wait_for_operation(
                client=client_under_test,
                operation_id=payloads.OPERATION_ID,
                poll_interval_ms=1,
                timeout_s=1,
                sleep=sleep,
                monotonic=monotonic,
            )

    assert CliResult.failed(timed_out.value.problem).exit_code is ExitCode.TIMED_OUT
    assert int(ExitCode.TIMED_OUT) == 10


def test_a_superseded_operation_read_from_the_api_exits_nine_and_names_its_successor() -> None:
    # Nine is only useful if it comes with the successor: an agent follows the chain rather than
    # dispatching another solve onto it. Read from a real server, and the code comes off the same
    # result the runner would exit by.
    with FakeApi() as api, httpx.Client(timeout=5.0) as client:
        api.answer(
            "GET",
            OPERATION_PATH,
            Answer.json(
                payloads.operation(status="superseded", superseded_by=payloads.SUCCESSOR_ID)
            ),
        )
        body = Transport(client).get(f"{api.base_url}{OPERATION_PATH}")

    superseded = Operation.read(body, "operation")

    assert CliResult.dispatched(superseded).exit_code is ExitCode.SUPERSEDED
    assert superseded.superseded_by == payloads.SUCCESSOR_ID
    assert payloads.SUCCESSOR_ID in superseded.summary


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
    path = home / ".config" / "syncr" / CREDENTIALS_FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({api_url: STORED_REFRESH}), encoding="utf-8")
    path.chmod(0o600)


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
