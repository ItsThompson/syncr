"""Running an external command, as one seam every module here takes by injection.

``pg_dump``, ``pg_restore``, ``gpg`` and ``rclone`` are the four tools this path is built out of,
and none of them can be exercised by a unit test on a machine that has to stay reproducible. So each
module takes a :class:`Run` and the suite passes a fake whose recorded calls ARE the assertion,
while the drill runs the real one end to end.

Streams go to and from FILES rather than through pipes, deliberately. A 100 MB dump through
``subprocess.PIPE`` is a 100 MB Python string, and worse, a pipe that closes mid-stream produces a
short file and a zero exit status from the reader's side: exactly the "succeeded and wrote nothing"
shape ``ops.verify`` exists to catch. With a file, ``pg_dump``'s own exit status is the writer's.
"""

from __future__ import annotations

import subprocess
from contextlib import ExitStack
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path


class CommandFailed(Exception):
    """A command exited non-zero, with what it said on stderr."""


@dataclass(frozen=True, slots=True)
class Result:
    """What one command did."""

    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class Run(Protocol):
    """The seam. One call, one command, no shell."""

    def __call__(
        self,
        argv: Sequence[str],
        *,
        stdout_path: Path | None = None,
        stdin_path: Path | None = None,
        environ: Mapping[str, str] | None = None,
        check: bool = True,
    ) -> Result: ...


def run(
    argv: Sequence[str],
    *,
    stdout_path: Path | None = None,
    stdin_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
    check: bool = True,
) -> Result:
    """Run one command. No shell, so nothing here can be quoted wrong into something else."""
    with ExitStack() as streams:
        out = streams.enter_context(stdout_path.open("wb")) if stdout_path else subprocess.PIPE
        into = streams.enter_context(stdin_path.open("rb")) if stdin_path else None
        completed = subprocess.run(  # noqa: S603 - argv is built here, never a shell string
            list(argv),
            stdout=out,
            stdin=into,
            stderr=subprocess.PIPE,
            env=dict(environ) if environ is not None else None,
            check=False,
        )
    result = Result(
        argv=tuple(argv),
        returncode=completed.returncode,
        stdout=_text(completed.stdout),
        stderr=_text(completed.stderr),
    )
    if check and result.returncode != 0:
        raise CommandFailed(f"{argv[0]} exited {result.returncode}: {result.stderr.strip()}")
    return result


def _text(raw: bytes | None) -> str:
    return "" if raw is None else raw.decode("utf-8", errors="replace")
