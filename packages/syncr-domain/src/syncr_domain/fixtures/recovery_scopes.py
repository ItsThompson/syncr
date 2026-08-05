"""The ``recovery_scopes`` fixture: one recovery window, declared both ways, at one anchor time.

A recovery window is the only forbidden span whose scope the user chooses, and the choice changes
which figures subtract it. Declared over every Area it is unavailable to all, so it leaves the
discretionary denominator. Declared over named Areas it is capacity for every other Area, so it
stays in the denominator and bites only the Areas it names. **One anchor time, two declarations**,
because a test comparing the two must vary the scope and nothing else.

``Europe/London`` 2026-W07. The commitment is the interview the settled records render, Wednesday
11 February 16:00-16:45, and its type casts 75 minutes of recovery afterwards: 16:45-18:00.

| Declaration | Forbids | Denominator | The probe reads it as |
|---|---|---|---|
| `scope: all` | every Area, including ones declared later | subtracted | `absolute_forbidden` |
| `scope: areas` | Study only | stays in | a `scoped_forbidden` window |

Both forms are :class:`~syncr_domain.gaps.ForbiddenWindow` values, which is what the assembler
produces and what the constraint checker reads, so the same two spans serve the denominator's
subtraction table, the per-Area legality rule, and the probe's projection of them.

**The asymmetry is the whole fixture.** Converting the scoped form to the absolute one may only
take capacity away: from Study, nothing, because Study was already forbidden; from every other
Area, the whole 75 minutes. A figure that moved the other way under that conversion would be
subtracting a scoped window from a whole-week total, which manufactures a shortfall the week does
not have.

Every instant is a **literal**, as in the other fixtures here, and
``tests/test_recovery_scopes_fixture.py`` re-derives each from the stated wall time.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final
from uuid import UUID

from syncr_domain.feasibility.inputs import ScopedWindow
from syncr_domain.gaps import ForbiddenKind, ForbiddenScope, ForbiddenWindow
from syncr_domain.intervals import Interval
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from syncr_domain.identifiers import AnchorId, AreaId

WEEK: Final = IsoWeek(2026, 7)

# Stand-ins for the Areas and the commitment a tenant would have declared. Fixed rather than
# generated, so a failure message names the same identifier on every run.
STUDY: Final[AreaId] = UUID("cccccccc-0000-4000-8000-000000000001")
FITNESS: Final[AreaId] = UUID("cccccccc-0000-4000-8000-000000000002")
ADMIN: Final[AreaId] = UUID("cccccccc-0000-4000-8000-000000000003")
ANCHOR: Final[AnchorId] = UUID("cccccccc-0000-4000-8000-00000000000a")

LABEL: Final = "recovery · Kontron Interview"
RECOVERY_MINUTES: Final = 75

SPAN: Final = Interval(datetime(2026, 2, 9, tzinfo=UTC), datetime(2026, 2, 16, tzinfo=UTC))
COMMITMENT: Final = Interval(
    datetime(2026, 2, 11, 16, 0, tzinfo=UTC), datetime(2026, 2, 11, 16, 45, tzinfo=UTC)
)
RECOVERY: Final = Interval(
    datetime(2026, 2, 11, 16, 45, tzinfo=UTC), datetime(2026, 2, 11, 18, 0, tzinfo=UTC)
)

FORBIDDING_EVERY_AREA: Final = ForbiddenWindow(
    interval=RECOVERY,
    kind=ForbiddenKind.RECOVERY,
    scope=ForbiddenScope.ALL,
    forbidden_area_ids=(),
    label=LABEL,
    anchor_id=ANCHOR,
)

FORBIDDING_STUDY: Final = ForbiddenWindow(
    interval=RECOVERY,
    kind=ForbiddenKind.RECOVERY,
    scope=ForbiddenScope.AREAS,
    forbidden_area_ids=(STUDY,),
    label=LABEL,
    anchor_id=ANCHOR,
)

# The probe's reading of the scoped form. The absolute form reaches it inside `absolute_forbidden`,
# which is an interval set rather than a typed collection, so it needs no projection here.
SCOPED: Final = ScopedWindow(interval=RECOVERY, forbidden_area_ids=(STUDY,))
