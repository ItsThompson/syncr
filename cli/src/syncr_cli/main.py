"""The entrypoint: parse, dispatch, render once, exit with the number the result asks for.

Four failures are answered here rather than by a traceback, and each arrives as the same wrapper
a success does, so ``--json`` answers with a document whatever happened.

| Failure | Becomes |
|---|---|
| A bad flag or a bad setting | ``syncr:cli-usage``, exit 2 |
| A refusal from the api | the api's own problem details, exit by its type |
| A response this build cannot read | ``syncr:cli-malformed-response``, exit 1 |
| A domain rule refusing a value the api sent | the same, exit 1 |

**A failure before the command line is understood is rendered in the format the machine implies.**
The flags are what a parse produces, so a parse that failed has none of them: the format is then
the configured one where the configuration is readable, and the terminal test where it is not.

**An unexpected exception is left alone.** Python exits 1 for one, which is exactly "generic
failure", and the traceback is the most useful thing a bug report can carry. Every anticipated
failure is one of the four above.

**No command prompts, ever.** Not merely when stdout is not a terminal: nothing in this package
reads stdin, which is a stronger guarantee than the rule asks for and one a test can assert.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from syncr_cli.config_file import config_path, read_config
from syncr_cli.errors import CliError, MalformedResponse
from syncr_cli.http import Transport
from syncr_cli.parser import parse
from syncr_cli.rendering.human import render_human
from syncr_cli.rendering.json_output import render_json
from syncr_cli.results import CliResult
from syncr_cli.runtime import Host, Runtime
from syncr_cli.settings import Flags, OutputFormat, resolve_settings
from syncr_domain.errors import DomainError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_cli.exit_codes import ExitCode


def main() -> None:
    """The console script. Reads the real environment and exits the process."""
    with Transport.opened() as transport:
        code = run(
            sys.argv[1:],
            host=Host.real(sys.stdout, sys.stderr, dict(os.environ)),
            transport=transport,
        )
    sys.exit(int(code))


def run(argv: Sequence[str], *, host: Host, transport: Transport) -> ExitCode:
    """One invocation, from arguments to exit code, writing to ``host``'s streams."""
    try:
        invocation, handler = parse(argv)
        runtime = Runtime.build(host=host, flags=invocation.flags, transport=transport)
    except CliError as error:
        return _write(CliResult.failed(error.problem), host=host, output=_early_format(host))
    try:
        result = handler(runtime, invocation)
    except CliError as error:
        result = CliResult.failed(error.problem)
    except DomainError as error:
        result = CliResult.failed(
            MalformedResponse(
                f"the API sent a value this CLI cannot use: {error}. Nothing was changed."
            ).problem
        )
    return _write(result, host=host, output=runtime.settings.output)


def _write(result: CliResult, *, host: Host, output: OutputFormat) -> ExitCode:
    """Render the result to stdout, and answer with the code it asks for."""
    rendered = render_json(result) if output is OutputFormat.JSON else render_human(result)
    host.stdout.write(rendered)
    host.stdout.flush()
    return result.exit_code


def _early_format(host: Host) -> OutputFormat:
    """The output format for a failure that happened before the flags were understood.

    The configured format where the configuration can be read, because a machine that states
    ``output = "json"`` means it for its usage errors too. The terminal test where it cannot,
    since a configuration file is exactly what may have just been refused.
    """
    try:
        return resolve_settings(
            flags=Flags(),
            env=host.env,
            config=read_config(config_path(dict(host.env), host.home)),
            stdout_is_tty=host.stdout_is_tty,
            today=host.today,
        ).output
    except CliError:
        return OutputFormat.HUMAN if host.stdout_is_tty else OutputFormat.JSON
