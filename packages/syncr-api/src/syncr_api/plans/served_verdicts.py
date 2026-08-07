"""Which verdict a READ serves, and the one rule that decides between two of them.

A read serves the **pending slot's** verdict when the slot holds one and its ``input_version`` is
the week's current one, and otherwise computes a live probe verdict from a fresh assembly.

## Why the slot rather than a fresh probe every time

The alternative is what the route table describes, and it computes a probe verdict on every read.
That yields ``provenance = "probe"`` always, so a week that passed the probe and then failed to
PACK would report the capacity check forever and never the stronger finding. ``US-FEAS-02``
requires the opposite: the stronger finding replaces the reading once the solve lands, and states
that the earlier reading was a capacity check. ``VE8`` exists for the same reason from the metric's
side -- a fresh probe would flip provenance back from ``solver`` after every solve.

The only place a solver verdict is persisted is ``PendingProposal.verdict``, and approval clears
that slot. So serving the slot is not a preference between two readings: it is the only reading
that can report a packing failure at all, and the fallback is not a second choice but what an empty
slot leaves.

## Both branches write nothing

``VE6``. No revision, no operation, no version bump, and no ``VerdictEvent``. Reading the slot is a
select; the fallback assembles and probes, and the assembler writes nothing by construction. A
transition a read observes is recorded by the next mutation or by the maintainer's next tick, at
most one tick later, which is the same answer the design gives for the tradeoff path's refusal.

## The slot and the version are both passed in, and for one reason

A caller reports both on the same response. Two statements reading either of them inside one
request take two snapshots under ``READ COMMITTED``, and the pair would then disagree: a payload
could offer a proposal to assent to beside a verdict computed as though the slot were empty. So this
module reads neither. Each caller reads each once and hands both in, which also makes the composed
read's slot query one query rather than two.

## A week with no plan has no verdict, on every caller

Nothing has been computed about such a week. Both callers apply that check BEFORE reaching the rule
above, so the biconditional the week's own read states holds on the backlog too: a column that
marked a task at risk on a week with no verdict would put a shortfall on one screen that the other
has no panel to show it on.

## The cost, and which branch pays it

The slot branch is free to this module. The fallback is a whole assembly, which is eighteen
resolutions over nineteen reads and the dominant cost of any request that probes, plus arithmetic
that is sub-millisecond beside it. Both callers are reads with a p95 budget, so the branch that
pays is the one whose week has a plan and no current proposal -- which is every week between an
approval and the next solve.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.plans.stored_verdicts import verdict_of
from syncr_api.user_settings.zone_reading import local_date
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.core.clock import Clock
    from syncr_api.plans.assembler import WeekAssembler
    from syncr_api.plans.proposals import PendingProposalRepository
    from syncr_api.plans.records import PendingProposalRecord
    from syncr_api.plans.repository import PlanRepository
    from syncr_api.plans.verdicts import WeekProbe
    from syncr_api.plans.versions import WeekInputVersionRepository
    from syncr_api.user_settings.repository import SettingsRepository
    from syncr_domain.feasibility import Verdict


class ServedVerdict:
    """The verdict one week's read answers with. Reads only, on both branches."""

    def __init__(self, *, assembler: WeekAssembler, probe: WeekProbe) -> None:
        self._assembler = assembler
        self._probe = probe

    async def for_week(
        self,
        iso_week: IsoWeek,
        *,
        now: datetime,
        input_version: int,
        held: PendingProposalRecord | None,
    ) -> Verdict:
        """The slot's verdict while it is current, else what capacity arithmetic can prove now.

        The live branch enumerates the tradeoffs beside the verdict, because a gap the user can do
        nothing about is a refusal without a remedy and the enumeration is pure over the assembly
        that has already been paid for. The slot's verdict is served exactly as the solve wrote it:
        a concession sized against a fresh assembly would not be the one that closes the gap this
        verdict names.
        """
        if held is not None and held.input_version == input_version:
            return verdict_of(held.verdict)
        assembled = await self._assembler.assemble(iso_week, now)
        return self._probe.offered_verdict_for(assembled).verdict


class CurrentWeekVerdict:
    """The verdict of the week the tenant is living in, by the rule a week's read serves.

    What the backlog's at-risk column reads. It is the same rule and the same arithmetic as the
    verdict panel's, reached through the same collaborator, so a task cannot be at risk on one
    screen and fine on another: there is one computation rather than two that agree today.

    **A week with no plan has no verdict, here as on the week's own read.** Nothing has been
    computed about such a week, so nothing about it is known to be at risk, and a column that marked
    a task anyway would put a shortfall on one screen that the other has no panel to show. That
    state is not a corner: the plan horizon maintainer ticks every fifteen minutes, so every tenant
    that finishes setup lives in an unplanned current week until it next runs, and indefinitely
    whenever it is behind.

    **Which week that is, is resolved in the HOME zone**, from the same reading every backlog-wide
    mutation resolves it in. A week boundary in UTC is not a week boundary for a tenant thirteen
    hours east, and the two answers differ for thirteen hours of every day.
    """

    def __init__(
        self,
        *,
        served: ServedVerdict,
        revisions: PlanRepository,
        proposals: PendingProposalRepository,
        versions: WeekInputVersionRepository,
        settings: SettingsRepository,
        clock: Clock,
    ) -> None:
        self._served = served
        self._revisions = revisions
        self._proposals = proposals
        self._versions = versions
        self._settings = settings
        self._clock = clock

    async def read(self) -> Verdict | None:
        """The current week's verdict, or ``None`` when that week holds no plan.

        Writes nothing, and needs no solve to have completed. The plan check is first, so a week the
        maintainer has not reached costs one indexed read rather than a whole assembly.
        """
        now = self._clock()
        profile = await self._settings.read()
        week = IsoWeek.containing(local_date(now, profile.home_zone))
        if await self._revisions.latest(week) is None:
            return None
        return await self._served.for_week(
            week,
            now=now,
            input_version=await self._versions.tracked_version(week),
            held=await self._proposals.find(week),
        )
