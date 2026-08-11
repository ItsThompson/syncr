"""The week the drill's tenant lived, written through the paths a person's week is written through.

Five tables carry a restore drill's evidence, and every one of them is written here by the thing
that writes it in production: the horizon maintainer materializes the week, a solve fills its slot,
the outcome service records and confirms what happened in it, the pin service holds one block and
writes the edit event beside it in the same transaction, and the concession repository records the
one thing an approved tradeoff persists.

**The week is the one before the one holding today, and every instant is stated rather than read.**
Two facts force that. A slot the week has already reached is left unbound, so a solve is asked for
at an instant inside the week rather than after it, or nothing is ever placed. And a day the user
has not lived cannot be confirmed, so the days being answered for have to be behind the real clock.
One week satisfies both at once: it is entirely behind now, and the instant the plan is asked for is
inside it. Nothing here depends on which weekday the drill is run on.

**The concession is written through the repository an approval writes it through.** Requesting a
tradeoff persists nothing by design: the candidate rides on the operation and only an approval makes
it real. Reaching one through the request path needs a week short enough that syncr offers a
concession for it, which is a fixture with a capacity budget rather than a seeder, so what is
recorded here is the write itself, with the solve's own operation named as its cause.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from syncr_api.approvals.injection import build_approval_service
from syncr_api.horizon.maintainer import PlanHorizonMaintainer
from syncr_api.outcomes.declarations import Recording
from syncr_api.outcomes.injection import get_outcome_service
from syncr_api.pins.declarations import PinRequested
from syncr_api.pins.injection import build_pin_service
from syncr_api.plans.adjustments import WeekAdjustmentRepository
from syncr_api.plans.injection import build_week_service
from syncr_api.plans.pins import PinRepository
from syncr_api.plans.proposals import PendingProposalRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import plan_document
from syncr_api.solving.config import SOLVE
from syncr_api.solving.repository import OperationRepository
from syncr_api.solving.runner import SolveRunner
from syncr_domain.identity import BindingKind
from syncr_domain.outcomes import OutcomeState
from syncr_domain.plan import AdjustmentKind
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_api.core.principal import Principal
    from syncr_api.plans.records import BlockOutcomeRecord, WeekAdjustmentRecord
    from syncr_api.solving.records import OperationRecord
    from syncr_api.worker.main import WorkerContext
    from syncr_domain.identifiers import AreaId, HabitId, OperationId, TenantId
    from syncr_domain.plan import Block, PlanDocument

# How much of the drill's Area floor the concession excuses. A figure rather than a measurement: the
# row exists so a restore has a concession to bring back, and what a real one would excuse is
# decided by the shortfall that offered it.
FLOOR_BREACH_MINUTES: Final = 60


class NothingWasPlaced(Exception):
    """The solve left the week holding no habit occurrence, so there is no cursor to move."""


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
    def dates(self) -> tuple[date, ...]:
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


async def materialize(session: AsyncSession, tenant_id: TenantId, week: DrillWeek) -> bool:
    """Bring the week into range through the maintainer's own duty. True when it planned one.

    Its first read is what makes a repeat run cheap: a week that already holds a plan creates
    nothing.
    """
    planned = await PlanHorizonMaintainer(session, tenant_id, clock=lambda: week.planned_at).plan(
        week.iso_week, now=week.planned_at
    )
    return planned.planned == 1


async def request_a_solve(
    session: AsyncSession, principal: Principal, week: DrillWeek
) -> OperationRecord:
    """Ask for a plan for the week, as the re-solve control does: due now rather than debounced."""
    return await build_week_service(
        session, principal.tenant_id, clock=lambda: week.solved_at
    ).request_solve(principal, str(week.iso_week), immediate=True)


async def the_weeks_solve(
    session: AsyncSession, tenant_id: TenantId, week: DrillWeek
) -> OperationRecord | None:
    """The week's most recent solve, whatever became of it, or ``None`` when none survives.

    An operation is pruned at thirty days and a concession is permanent, so a database seeded long
    enough ago holds the second and not the first. That is what makes this a read rather than a
    value the run carries.
    """
    return await OperationRepository(session, tenant_id).latest_of(week.iso_week, kinds=(SOLVE,))


async def run_the_solve(context: WorkerContext, week: DrillWeek) -> None:
    """Drain the due solve through the worker's own duty, at the instant it was asked for."""
    await SolveRunner(clock=lambda: week.solved_at).drain(context)


async def adopt_a_proposal(session: AsyncSession, principal: Principal, week: DrillWeek) -> bool:
    """Approve whatever the solve proposed rather than applied. False when it proposed nothing.

    A solve whose answer only adds may be adopted without asking, and one that moves or drops
    something waits for assent. Which of the two this week gets is the authority rule's answer
    rather than the seeder's, so both are carried: the drill needs the occurrences live, and an
    approval is how a proposal becomes live.
    """
    held = await PendingProposalRepository(session, principal.tenant_id).find(week.iso_week)
    if held is None:
        return False
    await build_approval_service(session, principal.tenant_id, clock=lambda: week.lived_at).approve(
        principal, str(week.iso_week)
    )
    return True


async def live_plan(
    session: AsyncSession, tenant_id: TenantId, week: DrillWeek
) -> PlanDocument | None:
    """The week's plan of record, rebuilt through the domain's own constructor."""
    latest = await PlanRepository(session, tenant_id).latest(week.iso_week)
    return None if latest is None else plan_document(latest.document)


def occurrences_of(document: PlanDocument, habit_id: HabitId) -> tuple[Block, ...]:
    """Every block the plan places for one habit, earliest first."""
    return tuple(
        sorted(
            (
                block
                for block in document.blocks
                if block.binding.kind is BindingKind.HABIT and block.binding.entity_id == habit_id
            ),
            key=lambda block: block.interval.start,
        )
    )


async def record_what_happened(
    session: AsyncSession, principal: Principal, week: DrillWeek, occurrences: tuple[Block, ...]
) -> tuple[BlockOutcomeRecord, ...]:
    """One occurrence completed and, when the week holds a second, one skipped.

    Two states rather than one, because the cursor's arithmetic is only visible against both: a skip
    does not advance it, so a restore that lost the completion and kept the skip would come back
    with the same row count and a different variant.
    """
    if not occurrences:
        raise NothingWasPlaced(
            f"{week.iso_week} holds no occurrence of the drill's rotation habit, so no confirmed "
            "completion can be recorded and a restore would have no cursor to re-derive. The solve "
            "placed nothing: read the week's own verdict before seeding again"
        )
    service = get_outcome_service(principal, session)
    states = (OutcomeState.COMPLETED, OutcomeState.SKIPPED)
    return tuple(
        [
            await service.record(
                principal,
                block.id,
                Recording(
                    iso_week=str(week.iso_week),
                    state=state,
                    actual_minutes=None,
                    actual_interval=None,
                ),
            )
            for block, state in zip(occurrences, states, strict=False)
        ]
    )


async def confirm_the_days(
    session: AsyncSession, principal: Principal, occurrences: tuple[Block, ...]
) -> int:
    """Confirm each day an outcome was recorded on, which is what advances the cursor.

    Recording says what happened to a block; confirming the day is the user answering for all of it,
    and only a confirmed completion counts. Every day named here is behind the real clock, because
    the week is.
    """
    service = get_outcome_service(principal, session)
    days = dict.fromkeys(block.interval.start.date() for block in occurrences)
    for day in days:
        await service.confirm_day(principal, day)
    return len(days)


async def hold_a_pin(
    session: AsyncSession, principal: Principal, week: DrillWeek, block: Block
) -> None:
    """Pin one block where the plan already put it, which writes the edit event beside it.

    The pin and its edit event are one transaction, so this one call is what puts rows in both
    tables. The instant is inside the week and before the block, because a block that has begun
    cannot be pinned.
    """
    await build_pin_service(session, principal.tenant_id, clock=lambda: week.lived_at).pin(
        principal,
        str(week.iso_week),
        PinRequested(block_id=block.id, start=block.interval.start),
    )


async def already_pinned(session: AsyncSession, tenant_id: TenantId, week: DrillWeek) -> bool:
    """Whether the week already holds a pin.

    A pin row is an upsert on its block and an edit event is not: each expression of a preference is
    its own training label, so a seeder that pinned on every run would grow one table and not the
    other. Reading first is what keeps a repeat run from writing either.
    """
    return bool(await PinRepository(session, tenant_id).for_week(week.iso_week))


async def concede_a_floor_breach(
    session: AsyncSession,
    tenant_id: TenantId,
    week: DrillWeek,
    *,
    area_id: AreaId,
    operation_id: OperationId,
) -> WeekAdjustmentRecord:
    """Record the concession an approval records: this Area's floor, breached by agreement.

    An upsert on the week, the kind and the target, so a repeated drill re-states one row rather
    than accumulating them.
    """
    return await WeekAdjustmentRepository(session, tenant_id).upsert(
        iso_week=week.iso_week,
        kind=AdjustmentKind.BREACH_FLOOR.value,
        target_id=area_id,
        created_at=week.lived_at,
        created_by_operation_id=operation_id,
        delta_minutes=FLOOR_BREACH_MINUTES,
    )
