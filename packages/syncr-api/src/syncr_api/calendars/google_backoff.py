"""How long to wait before retrying Google, and how many times to bother.

Truncated exponential backoff with jitter, which is what Google's own guidance asks for: each wait
doubles, every wait is capped, and a random component up to a second stops a fleet of clients
retrying in synchronised waves.

Three properties are worth stating because each is a decision rather than the obvious reading:

**The retries are bounded, small, and per REQUEST.** The worker polls again on its own interval, so
a read that kept backing off would hold a tick open doing work the next tick redoes. Four attempts
covers a burst on ONE request; a sustained rate limit is a condition to report rather than to
outwait. The budget is per request rather than per read because a rate limit on page four is the
same condition as one on page one, and the aggregate bound across every page and every wait is the
read's own deadline.

**A provider's ``Retry-After`` wins, up to a ceiling.** Google knows when its window resets and
syncr does not, so an explicit wait is honoured. A wait longer than the ceiling is not: an answer
asking for ten minutes is asking for longer than a poll interval, so the read ends and the next
tick starts fresh.

**Sleeping is injected.** Every wait counts against the read's own deadline, and a test that had to
sleep for three of them would be a test of ``sleep``. The random source is injected for the same
reason: jitter that cannot be pinned makes an assertion about a wait impossible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from random import Random
from typing import TYPE_CHECKING, Final

from syncr_api.calendars.google_config import (
    BACKOFF_BASE_SECONDS,
    MAX_ATTEMPTS,
    MAX_BACKOFF_SECONDS,
    MAX_HONOURED_RETRY_AFTER_SECONDS,
    MAX_JITTER_SECONDS,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

_RETRY_AFTER_HEADER: Final = "Retry-After"


@dataclass(frozen=True, slots=True)
class BackoffPolicy:
    """The wait before attempt ``n``, and whether there is another attempt at all."""

    random: Random = field(default_factory=Random)

    def has_another_attempt(self, attempts: int) -> bool:
        """Whether a request that has been made ``attempts`` times may be made once more.

        ``attempts`` counts calls to ONE request, not calls in a read. A read that paginates spends
        its own budget per page and is bounded overall by its deadline.
        """
        return attempts < MAX_ATTEMPTS

    def wait_before(self, attempts: int, *, retry_after: float | None = None) -> float:
        """Seconds to wait before the next attempt, jitter included.

        ``attempts`` is how many calls have already been made, so the first wait is the base.
        """
        if retry_after is not None:
            return min(retry_after, MAX_HONOURED_RETRY_AFTER_SECONDS)
        doubled = BACKOFF_BASE_SECONDS * float(2 ** max(attempts - 1, 0))
        return min(doubled, MAX_BACKOFF_SECONDS) + self._jitter()

    def _jitter(self) -> float:
        return float(self.random.uniform(0, MAX_JITTER_SECONDS))


def stated_retry_after(headers: Mapping[str, str]) -> float | None:
    """The wait a response asked for, when it asked in seconds.

    The header is also allowed to carry an HTTP date, which is not read: converting one needs a
    clock and a date parser to answer a question the backoff schedule already answers safely. A
    date-form header therefore falls back to the exponential wait rather than to no wait at all.
    """
    stated = headers.get(_RETRY_AFTER_HEADER)
    if stated is None:
        return None
    try:
        seconds = float(stated.strip())
    except ValueError:
        return None
    return seconds if seconds >= 0 else None
