"""The runner: what format it writes in, what it does with a bad flag, and what it never does.

The properties here are the ones an agent depends on before it has read a byte of output: the
format is chosen without a flag, a usage error still answers with the wrapper, and nothing ever
waits for input.
"""

from __future__ import annotations

import builtins
import json
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from syncr_cli.errors import UsageError
from syncr_cli.exit_codes import ExitCode, exit_code_table
from syncr_cli.main import _write
from syncr_cli.parser import PROGRAM, build_parser
from syncr_cli.results import CliResult
from syncr_cli.runtime import Host
from syncr_cli.settings import OutputFormat, environment_variable
from syncr_domain.errors import DomainError
from tests.fake_api import FakeApi
from tests.harness import TODAY, drive

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_cli.wire.reading import JsonMapping

COMMANDS = [
    ["auth", "login"],
    ["auth", "logout"],
    ["auth", "status"],
    ["week", "show"],
]


def test_output_is_json_when_stdout_is_not_a_terminal(tmp_path: Path) -> None:
    with FakeApi() as api:
        ran = drive(["week", "show"], base_url=api.base_url, home=tmp_path)

    assert ran.document["ok"] is False


def test_output_is_human_when_stdout_is_a_terminal(tmp_path: Path) -> None:
    with FakeApi() as api:
        ran = drive(["week", "show"], base_url=api.base_url, home=tmp_path, stdout_is_tty=True)

    assert not ran.stdout.startswith("{")


def test_a_configured_format_governs_a_usage_error_too(tmp_path: Path) -> None:
    # A machine that states `output = "json"` means it for its usage errors as well, and the flags
    # are exactly what a failed parse does not have.
    config = tmp_path / ".config" / "syncr" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('output = "json"\n', encoding="utf-8")

    with FakeApi() as api:
        ran = drive(
            ["week", "show", "--nonsense"], base_url=api.base_url, home=tmp_path, stdout_is_tty=True
        )

    assert ran.code is ExitCode.USAGE
    assert ran.document["problem"]["type"] == "syncr:cli-usage"


def test_a_configuration_that_cannot_be_read_still_answers_in_a_format(tmp_path: Path) -> None:
    # The configuration file is exactly what may have just been refused, so the format falls back to
    # the terminal test rather than to reading it again.
    config = tmp_path / ".config" / "syncr" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text("output = \n", encoding="utf-8")

    with FakeApi() as api:
        ran = drive(["week", "show"], base_url=api.base_url, home=tmp_path)

    assert ran.code is ExitCode.USAGE
    assert ran.document["problem"]["detail"].startswith(str(config))


def test_a_bad_flag_is_a_usage_error_carrying_the_wrapper(tmp_path: Path) -> None:
    with FakeApi() as api:
        ran = drive(["week", "show", "--wek", "2026-W07"], base_url=api.base_url, home=tmp_path)

    assert ran.code is ExitCode.USAGE
    assert ran.document["ok"] is False
    assert list(ran.document) == ["ok", "data", "verdict", "operation", "problem"]
    assert "--help" in ran.document["problem"]["detail"]


def test_naming_no_command_is_a_usage_error(tmp_path: Path) -> None:
    with FakeApi() as api:
        ran = drive([], base_url=api.base_url, home=tmp_path)

    assert ran.code is ExitCode.USAGE
    assert "name a command" in ran.document["problem"]["detail"]


def test_naming_a_noun_with_no_verb_is_a_usage_error(tmp_path: Path) -> None:
    with FakeApi() as api:
        ran = drive(["auth"], base_url=api.base_url, home=tmp_path)

    assert ran.code is ExitCode.USAGE


def test_a_flag_stated_before_the_verb_is_not_overwritten_by_the_verbs_own(tmp_path: Path) -> None:
    # `syncr --json week show` is what a person types and `syncr week show --json` is what an agent
    # generates. They are the same invocation.
    with FakeApi() as api:
        before = drive(
            ["--json", "week", "show"], base_url=api.base_url, home=tmp_path, stdout_is_tty=True
        )
        after = drive(
            ["week", "show", "--json"], base_url=api.base_url, home=tmp_path, stdout_is_tty=True
        )

    assert before.stdout.startswith("{")
    assert after.stdout.startswith("{")


def test_an_api_that_cannot_be_reached_exits_eleven(tmp_path: Path) -> None:
    # A closed port is a real connection refusal, which is what "the API is unavailable" means.
    with FakeApi() as api:
        unreachable = api.base_url

    ran = drive(["week", "show"], base_url=unreachable, home=tmp_path)

    assert ran.code is ExitCode.API_UNAVAILABLE
    assert ran.document["problem"]["type"] == "syncr:cli-api-unreachable"


def test_an_api_url_that_names_no_host_exits_eleven(tmp_path: Path) -> None:
    ran = drive(["week", "show"], base_url="http://not-a-host.invalid", home=tmp_path)

    assert ran.code is ExitCode.API_UNAVAILABLE


def test_a_setting_stated_in_the_environment_is_honored(tmp_path: Path) -> None:
    with FakeApi() as api:
        ran = drive(
            ["week", "show"],
            base_url=api.base_url,
            home=tmp_path,
            env={environment_variable("week"): "2026-W54"},
        )

    assert ran.code is ExitCode.USAGE
    assert environment_variable("week") in ran.document["problem"]["detail"]


def test_a_payload_whose_rendering_raises_still_answers_with_the_wrapper() -> None:
    # The error boundary covers rendering, not only the command. `_write` is the one function whose
    # contract is "turn anything into the wrapper", and the only way to hand it a renderer that
    # raises is a payload that raises: every view implements this protocol, so a view that reaches a
    # domain rule and is refused by it is the case this exists for.
    #
    # The human format is what is driven, because it is the format that reaches the domain at all:
    # the JSON renderer emits the api's own object and calls no view method, which is exactly why an
    # unusable value has to be refused when the payload is read as well as caught here.
    stdout = StringIO()
    host = _host(stdout)

    code = _write(CliResult.succeeded(_RefusedByTheDomain()), host=host, output=OutputFormat.HUMAN)

    written = stdout.getvalue()
    assert code is ExitCode.FAILURE
    assert "Unreadable response" in written
    assert "cannot print" in written
    assert "Traceback" not in written


def test_the_same_payload_answers_the_json_wrapper_too() -> None:
    # No fallback happens here: the JSON renderer emits the api's own object and calls no view
    # method, so the payload that refuses to render for a person renders for an agent. That is why
    # the read-time refusal is the half that makes the two formats agree, and this the half that
    # stops the human one losing its wrapper.
    stdout = StringIO()

    code = _write(
        CliResult.succeeded(_RefusedByTheDomain()), host=_host(stdout), output=OutputFormat.JSON
    )

    document = json.loads(stdout.getvalue())
    assert code is ExitCode.SUCCESS
    assert list(document) == ["ok", "data", "verdict", "operation", "problem"]


def _host(stdout: StringIO) -> Host:
    return Host(
        env={},
        home=Path("/nowhere"),
        stdout=stdout,
        stderr=StringIO(),
        stdout_is_tty=False,
        today=TODAY,
    )


class _RefusedByTheDomain:
    """A payload whose rendering reaches a domain rule that refuses its value."""

    @property
    def payload(self) -> JsonMapping:
        return {}

    def header_lines(self) -> list[str]:
        raise DomainError("-5 minutes is not a duration, so it renders as nothing")

    def body_lines(self) -> list[str]:
        return []

    def render_deadline(self, moment: datetime) -> str:
        return moment.isoformat()


def test_a_render_time_refusal_keeps_its_own_exit_code() -> None:
    # A refusal that already knows its problem knows its exit code too. Flattening every render-time
    # failure into an unreadable-response would answer 1 for a usage error.
    stdout = StringIO()

    code = _write(
        CliResult.succeeded(_RefusesAsUsage()), host=_host(stdout), output=OutputFormat.HUMAN
    )

    assert code is ExitCode.USAGE
    assert "Usage error" in stdout.getvalue()


class _RefusesAsUsage(_RefusedByTheDomain):
    """A payload whose rendering raises a failure of this package's own."""

    def header_lines(self) -> list[str]:
        raise UsageError("--week names no ISO week")


@pytest.mark.parametrize("command", COMMANDS)
def test_no_command_ever_waits_for_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: list[str]
) -> None:
    # Stronger than "does not prompt when stdout is not a terminal": nothing in this package reads
    # stdin, so there is no condition under which a command can block on a person.
    def refuse(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("a command asked for input")

    monkeypatch.setattr(builtins, "input", refuse)

    with FakeApi() as api:
        drive(command, base_url=api.base_url, home=tmp_path, stdout_is_tty=True)


@pytest.mark.parametrize("command", COMMANDS)
def test_every_commands_help_states_its_examples_and_the_exit_code_table(
    command: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    # An agent needs no external documentation to orient itself, so the table is printed rather than
    # filed. Asserted on what `--help` writes, not merely on its exit code.
    with pytest.raises(SystemExit) as exited:
        build_parser().parse_args([*command, "--help"])

    printed = capsys.readouterr().out
    assert exited.value.code == 0
    assert "examples:" in printed
    assert exit_code_table() in printed
    assert f"{PROGRAM} {command[0]}" in printed
    assert "SYNCR_" in printed


def test_the_root_help_lists_every_noun(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--help"])

    printed = capsys.readouterr().out
    for noun in {command[0] for command in COMMANDS}:
        assert noun in printed
