"""Driving the CLI the way the process does: real argv, real HTTP, its own streams.

``drive`` runs :func:`syncr_cli.main.run` against a real socket, with the environment and the home
directory a test states. Nothing inside the package is patched, so what a test asserts is what a
user sees: the bytes on stdout, the notices on stderr, and the number the process exits with.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from io import StringIO
from typing import TYPE_CHECKING, Any

import httpx

from syncr_cli.http import Transport
from syncr_cli.main import run
from syncr_cli.runtime import Host

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from syncr_cli.exit_codes import ExitCode
    from syncr_cli.runtime import BrowserOpener

# A Tuesday inside 2026-W07, which is the week every payload in `payloads` is about. Fixed, so no
# assertion here depends on the day the suite is run.
TODAY = date(2026, 2, 10)


def _no_browser(_url: str) -> bool:
    """The default for a test: nothing opens, so no suite run can launch a real browser.

    A test that needs the code to arrive supplies a browser that delivers it.
    """
    return False


@dataclass(frozen=True, slots=True)
class Ran:
    """What one invocation produced."""

    code: ExitCode
    stdout: str
    stderr: str

    @property
    def document(self) -> dict[str, Any]:
        """stdout as the JSON document ``--json`` writes."""
        parsed = json.loads(self.stdout)
        assert isinstance(parsed, dict)
        return parsed

    @property
    def lines(self) -> list[str]:
        return self.stdout.splitlines()


def drive(
    argv: Sequence[str],
    *,
    base_url: str,
    home: Path,
    env: Mapping[str, str] | None = None,
    stdout_is_tty: bool = False,
    today: date = TODAY,
    open_browser: BrowserOpener = _no_browser,
) -> Ran:
    """Run one invocation against ``base_url`` and answer with everything it produced."""
    stdout, stderr = StringIO(), StringIO()
    environment = {"SYNCR_API_URL": base_url, **(env or {})}
    host = Host(
        env=environment,
        home=home,
        stdout=stdout,
        stderr=stderr,
        stdout_is_tty=stdout_is_tty,
        today=today,
        open_browser=open_browser,
    )
    with httpx.Client(timeout=5.0) as client:
        code = run(list(argv), host=host, transport=Transport(client))
    return Ran(code=code, stdout=stdout.getvalue(), stderr=stderr.getvalue())
