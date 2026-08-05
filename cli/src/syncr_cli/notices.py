"""What the process says beyond its result, and the stream it says it on.

Two things have to reach the user that are not the answer to their command: the URL of a consent
screen they are waiting to approve, and the fact that a credential is being kept in a file
because this machine has no keychain. Both go to stderr, immediately.

**stderr, because stdout is the result.** An agent parses stdout, and a notice there would
corrupt a document it is reading.

**Immediately, because a notice held until the end is not a notice.** The consent URL is needed
while the flow waits, not after it.

**Once each.** A store consulted twice in one process states its fallback once, so the output is
the same whatever a command happened to read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import TextIO


class Notices:
    """The stderr channel, with each notice stated at most once."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self._stated: list[str] = []

    @property
    def stated(self) -> tuple[str, ...]:
        """Every notice this process has written, in order."""
        return tuple(self._stated)

    def state(self, notice: str) -> None:
        if notice in self._stated:
            return
        self._stated.append(notice)
        self._stream.write(f"{notice}\n")
        self._stream.flush()
