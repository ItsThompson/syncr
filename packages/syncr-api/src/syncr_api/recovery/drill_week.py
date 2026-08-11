"""Which week the drill's evidence describes, and the instant each act in it is stated at.

**The week is the one before the one holding today, and every instant is stated rather than read.**
Two facts force that. A slot the week has already reached is left unbound, so a solve is asked for
at an instant inside the week rather than after it, or nothing is ever placed. And a day the user
has not lived cannot be confirmed, so the days being answered for have to be behind the real clock.
One week satisfies both at once: it is entirely behind now, and the instant the plan is asked for is
inside it. Nothing here depends on which weekday the drill is run on.

Its own module because three others read it and none of them owns it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from datetime import date as Date


@dataclass(frozen=True, slots=True)
class DrillWeek:
    """The week the drill's evidence describes, and the instant each act is stated at.

    Three instants rather than one, and they are ordered because the live plan is. A revision is the
    live plan when it is the newest, and two revisions sharing an instant are ordered by their
    identifiers, so a materialization and the solve that fills it are stated minutes apart or which
    of the two a reader calls live is decided by a random UUID. All three are inside the week's
    first hour, which is before every slot it holds: a slot the week has already reached is left
    unbound, and a block that has begun cannot be pinned.
    """

    iso_week: IsoWeek
    planned_at: datetime
    solved_at: datetime
    lived_at: datetime

    @property
    def dates(self) -> tuple[Date, ...]:
        return self.iso_week.dates()


def the_week_behind(now: datetime) -> DrillWeek:
    """The whole week before the one holding ``now``: every day of it is behind the real clock."""
    iso_week = IsoWeek.containing(now.astimezone(UTC).date()).preceding()
    monday = datetime.combine(iso_week.monday(), datetime.min.time(), tzinfo=UTC)
    return DrillWeek(
        iso_week=iso_week,
        planned_at=monday,
        solved_at=monday + timedelta(minutes=5),
        lived_at=monday + timedelta(hours=1),
    )
