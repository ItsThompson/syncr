"""The week the drill's tenant lived, written through the paths a person's week is written through.

Five tables carry a restore drill's evidence, and every one of them is written by the thing that
writes it in production: the horizon maintainer materializes the week, a solve fills its slot, the
outcome service records and confirms what happened in it, the pin service holds one block and writes
the edit event beside it in the same transaction, and the concession is
:mod:`syncr_api.recovery.drill_concession`.

**Every step reads before it writes**, so a repeat run writes nothing at all: the plan, the solve,
the outcomes, the pin and the concession each have a read that answers whether the thing is already
there. Which week and which instants are :mod:`syncr_api.recovery.drill_week`'s.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.approvals.injection import build_approval_service
from syncr_api.core.settings import DEFAULT_SOLVE_DEBOUNCE_MS
from syncr_api.horizon.maintainer import PlanHorizonMaintainer
from syncr_api.outcomes.declarations import Recording
from syncr_api.outcomes.injection import build_outcome_service
from syncr_api.pins.declarations import PinRequested
from syncr_api.pins.injection import build_pin_service
from syncr_api.plans.injection import build_week_service
from syncr_api.plans.pins import PinRepository
from syncr_api.plans.proposals import PendingProposalRepository
from syncr_api.plans.reality import BlockOutcomeRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import plan_document
from syncr_api.solving.config import SOLVE
from syncr_api.solving.injection import debounce_window
from syncr_api.solving.repository import OperationRepository
from syncr_api.solving.runner import SolveRunner
from syncr_domain.identity import BindingKind
from syncr_domain.intervals import Interval
from syncr_domain.outcomes import OutcomeState

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_api.core.principal import Principal
    from syncr_api.plans.records import BlockOutcomeRecord
    from syncr_api.recovery.drill_week import DrillWeek
    from syncr_api.solving.records import OperationRecord
    from syncr_api.worker.main import WorkerContext
    from syncr_domain.identifiers import HabitId, TenantId
    from syncr_domain.plan import Block, PlanDocument


class NothingWasPlaced(Exception):
    """The solve left the week holding no habit occurrence, so there is no cursor to move."""


async def materialize(session: AsyncSession, tenant_id: TenantId, week: DrillWeek) -> bool:
    """Bring the week into range through the maintainer's own duty. True when it asked for one.

    Its first read is what makes a repeat run cheap: a week that already holds a plan creates
    nothing. Asking is all the step does now -- the solve itself is the next one, which the run's
    own request joins and the drain that follows claims.
    """
    planned = await PlanHorizonMaintainer(
        session,
        tenant_id,
        clock=lambda: week.planned_at,
        # The run pulls the solve due itself on the very next step, so the shipped default window
        # here is never waited out.
        debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
    ).plan(week.iso_week, now=week.planned_at)
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


def require_occurrences(occurrences: tuple[Block, ...], week: DrillWeek) -> None:
    """Refuse a week the solve left empty. Answers nothing: it is a check rather than a reading.

    One raiser rather than a check per caller, and it is called twice on purpose: once by the
    sequence, as soon as the solve's answer has been read, and once by the recording, which is the
    step whose meaning depends on it. The first is what a composed run refuses on, because the steps
    between the two index the occurrences and would raise something else first; the second is what
    keeps the function answerable for its own argument.
    """
    if occurrences:
        return
    raise NothingWasPlaced(
        f"{week.iso_week} holds no occurrence of the drill's rotation habit, so no confirmed "
        "completion can be recorded and a restore would have no cursor to re-derive. The solve "
        "placed nothing: read the week's own verdict before seeding again"
    )


async def already_answered_for(
    session: AsyncSession, tenant_id: TenantId, occurrences: tuple[Block, ...]
) -> bool:
    """Whether every occurrence already carries a CONFIRMED outcome.

    The read the recording and the confirmation need, and confirmed rather than merely recorded is
    the whole of it: a run that recorded and then stopped leaves rows a repeat has to confirm, and
    only a confirmed completion moves the cursor. So a half-answered week is answered again and a
    fully answered one is left alone.

    Without it both steps run on every repeat, and each ends by bumping every tracked week from the
    one holding the clock onwards. The drill's week is behind the clock, so nothing moves while
    nothing at or after the clock is tracked, and a version counter moves the moment something is.

    The span is the occurrences' own rather than the week's, so it needs no reading of the tenant's
    zones to know which instants the week covers.
    """
    if not occurrences:
        return False
    span = Interval(
        min(block.interval.start for block in occurrences),
        max(block.interval.end for block in occurrences),
    )
    recorded = {
        row.block_id: row for row in await BlockOutcomeRepository(session, tenant_id).for_span(span)
    }
    return all(block.id in recorded and recorded[block.id].is_confirmed for block in occurrences)


async def record_what_happened(
    session: AsyncSession, principal: Principal, week: DrillWeek, occurrences: tuple[Block, ...]
) -> tuple[BlockOutcomeRecord, ...]:
    """One occurrence completed and, when the week holds a second, one skipped.

    Two states rather than one, because the cursor's arithmetic is only visible against both: a skip
    does not advance it, so a restore that lost the completion and kept the skip would come back
    with the same row count and a different variant.
    """
    require_occurrences(occurrences, week)
    service = build_outcome_service(
        session,
        principal.tenant_id,
        debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
    )
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
    service = build_outcome_service(
        session,
        principal.tenant_id,
        debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
    )
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
