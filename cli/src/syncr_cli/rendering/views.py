"""What every payload without a week around it shares: no body group, and a plain instant.

Two of the four members of :class:`~syncr_cli.results.Rendered` have one answer for most commands. A
payload that carries no zone map cannot name ``Fri 09:00`` for an instant, because the wall time
depends on the zone the user is in on that date, and a surface that guessed one would print a time
nobody's clock showed. And a payload whose whole answer is a heading has nothing to print below a
verdict.

Stated once here rather than on each view, so a new view inherits both answers and overrides only
what it actually has.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_cli.rendering.human import iso_deadline

if TYPE_CHECKING:
    from datetime import datetime


class PlainView:
    """A payload with no body group and no zone map.

    ``__slots__`` is empty and present: without it, a ``slots=True`` dataclass inheriting from this
    would gain a ``__dict__`` and the declaration would buy nothing.
    """

    __slots__ = ()

    def body_lines(self) -> list[str]:
        return []

    def render_deadline(self, moment: datetime) -> str:
        return iso_deadline(moment)
