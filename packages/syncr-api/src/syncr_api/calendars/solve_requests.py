"""Asking for a solve of the weeks a sync pass invalidated.

A pass that moved a commitment bumps the input version of every week whose occupancy moved, and the
bump on its own is only half of what such a week needs. The version is the guard a running solve's
conditional write is made against, so a bump nothing acts on leaves the week in the state that looks
most like work: the solve that was running is superseded, nothing replaces it, and the grid keeps
drawing solver-placed blocks around commitments that have moved under them. So the pass that bumps
asks for the pass that reads the new occupancy.

**Only the weeks the bump moved.** A week with no version row is not tracked: it has no plan and no
running solve to invalidate, which is why the counter leaves it alone. A solve of one would produce
a plan for a week nothing has planned, so this asks for the same set the counter wrote. That also
bounds the cardinality by what the tenant has PLANNED rather than by how long a published component
happens to be: an accepted component is bounded in days, not in weeks, so one of them can occupy
every week of a century.

**The set is read back rather than carried out of the counter.** The counter answers with nothing --
it enumerates the tracked weeks of a range, writes them, and returns -- and widening that answer
would change the one method every mutating service in this api holds. One enumeration over the span
this pass touched, intersected with the weeks it changed, is the smaller change and costs one
statement.

**Nothing is asked for immediately.** A request that carries no candidate and finds an operation
already pending leaves its due instant where it is, so several feeds landing in one tick resolve
into one solve per week rather than one per feed. A poll is not a person waiting for an answer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_common.logging import get_logger

if TYPE_CHECKING:
    from syncr_api.plans.versions import WeekInputVersionRepository
    from syncr_api.solving.coordinator import SolveCoordinator
    from syncr_domain.weeks import IsoWeek

_log = get_logger("syncr.calendars")


class TrackedWeekSolves:
    """The solve each week a sync invalidated needs, asked for once per week."""

    def __init__(self, versions: WeekInputVersionRepository, coordinator: SolveCoordinator) -> None:
        self._versions = versions
        self._coordinator = coordinator

    async def request(self, weeks: frozenset[IsoWeek]) -> tuple[IsoWeek, ...]:
        """Ask for a solve of every tracked week in ``weeks``, earliest first.

        Answers with the weeks it asked for, and **the sync pass does not read that answer**, the
        same as the collision detection's: the counts a pass reports come from the fetch outcome and
        the sync state.

        An empty set takes no statement at all, which is what a poll of a steady feed is: fifteen
        minutes later the same feed republishes the same components, nothing moved, and no operation
        exists for the next pass to supersede.

        The enumeration is one read over the whole span rather than one per week, so a year-long
        component costs the same as an hour-long one. It reaches weeks between two commitments a
        fortnight apart, which the intersection then drops: those weeks hold plans this pass left
        alone.
        """
        if not weeks:
            return ()
        tracked = await self._versions.tracked_weeks(min(weeks), max(weeks))
        asked = tuple(week for week in tracked if week in weeks)
        for week in asked:
            await self._coordinator.request_solve(week, await self._versions.tracked_version(week))
        _log.info(
            "calendars.sync.solves_requested",
            weeks_invalidated=len(weeks),
            weeks_requested=len(asked),
        )
        return asked
