"""The habit service: authorization, the entity's invariants, and the version bump.

Four rules live here rather than anywhere else.

**A habit is validated by building the entity.** X3 and X4 are a relation between a habit's own
binding source and its variant list, so they are stated once in ``syncr_domain.habits`` and
applied by constructing a ``Habit`` from the merged values before anything is written. A rule
restated in a request schema would be a second, weaker statement of this one, and a schema
cannot see a stored value a ``PATCH`` left alone.

**A habit is validated against its Area, not against its request.** The Area has to exist and it
has to be this tenant's, which is a comparison between two stored rows.

**Every mutation is a solve-input mutation.** A habit's cadence, duration, and binding source are
read by the week assembler and reach the solver as occurrences, so declaring, changing, or
removing one bumps the week input version from the current week onwards. Past weeks are not
touched: an approved revision is immutable and keeps the inputs it was computed with. A title
change bumps too, and that is deliberate rather than an oversight: a title reaches the solver as
the occurrence's own label, so unlike an Area rename there is no reading under which the solver
cannot see it.

**Nothing here writes a cursor, and no method could.** It is derived on read, from the outcome
log, through the pure functions in ``syncr_domain``, and it stays that way: a cursor survives no
window, so dropping one completion from any read would move every later week onto the wrong
variant. The debt figure is different: it is stored on the habit row as ``charged_misses`` and
restated by the outcome write (:mod:`syncr_api.habits.charged`), so a response answers with what
the log supports without walking its whole history. Neither has a write path in this module, so
"no API path sets either by hand" is a property of the shape rather than a rule a reviewer has
to check per route.

``authorize_tenant`` is called on the one row a caller addresses by identifier. Every row these
methods touch was fetched through a repository scoped to the principal's own tenant, so its
``tenant_id`` IS the principal's, and the scoped ``SELECT`` is what turns another tenant's
identifier into a 404 rather than an edit. The call is defense in depth rather than the check
producing that 404.

``require_scope`` denies nothing over HTTP today, and that is a property of the credential rather
than of the check: every route reaching these methods resolves a browser session, and a session
carries every scope because the user is acting directly. The check becomes live the first time a
bearer credential reaches one of these routes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from syncr_api.core.errors import NotFound
from syncr_api.core.principal import authorize_tenant, require_scope
from syncr_api.core.scopes import Scope
from syncr_api.habits.config import HABIT_RESOURCE
from syncr_api.habits.rules import stated_rejection, unknown_area_for_a_habit
from syncr_common.logging import get_logger
from syncr_common.metrics import measured
from syncr_domain.cursor import CursorReading, cursor_reading
from syncr_domain.debt import DebtReading, stored_reading

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from syncr_api.areas.repository import AreaRepository
    from syncr_api.core.clock import Clock
    from syncr_api.core.principal import Principal
    from syncr_api.habits.declarations import HabitChange, HabitDeclaration
    from syncr_api.habits.outcome_log import HabitOutcomeReader
    from syncr_api.habits.records import HabitRecord
    from syncr_api.habits.repository import HabitRepository
    from syncr_api.horizon.projection import ProjectionHorizon
    from syncr_api.user_settings.solve_inputs import BacklogWideBump, RequestsASolve
    from syncr_domain.identifiers import AreaId, HabitId
    from syncr_domain.outcomes import HabitOutcome

_log = get_logger("syncr.habits")


@dataclass(frozen=True, slots=True)
class ReadHabit:
    """One habit, with the two figures a response renders beside it.

    Both are answered in one call over one set of stored facts, so a response cannot show a
    cursor from one read and a debt figure from another. They differ in where each lives: the
    cursor derives from the log here, and the debt reads the stored charge the outcome write
    maintains.
    """

    habit: HabitRecord
    cursor: CursorReading | None
    debt: DebtReading


class HabitService:
    """Read and change one tenant's habits, and derive what the outcome log says about them."""

    def __init__(
        self,
        habits: HabitRepository,
        areas: AreaRepository,
        outcomes: HabitOutcomeReader,
        bump: BacklogWideBump,
        solve_requests: RequestsASolve,
        horizon: ProjectionHorizon,
        clock: Clock,
    ) -> None:
        self._habits = habits
        self._areas = areas
        self._outcomes = outcomes
        self._bump = bump
        self._solve_requests = solve_requests
        self._horizon = horizon
        self._clock = clock

    @measured("habits")
    async def list_all(
        self, principal: Principal, *, area_id: AreaId | None = None
    ) -> tuple[ReadHabit, ...]:
        """Every habit, or the ones inside one Area, each with its cursor and its debt.

        One outcome-log read for the whole collection rather than one per habit, because both
        derivations filter the log themselves and reading it once is what keeps a list of twenty
        habits a single query.
        """
        require_scope(principal, Scope.PLAN_READ)
        found = await self._habits.list_all(area_id=area_id)
        return await self._read_all(found)

    @measured("habits")
    async def read(self, principal: Principal, habit_id: HabitId) -> ReadHabit:
        """One habit of this tenant's, or a 404 that discloses nothing about another's."""
        require_scope(principal, Scope.PLAN_READ)
        return (await self._read_all((await self._require_habit(principal, habit_id),)))[0]

    @measured("habits")
    async def create(self, principal: Principal, declaration: HabitDeclaration) -> ReadHabit:
        """Declare a habit inside an Area that already exists, and invalidate future weeks."""
        require_scope(principal, Scope.ADMIN)
        now = self._clock()
        if await self._areas.find(declaration.area_id) is None:
            raise unknown_area_for_a_habit()
        with stated_rejection():
            # Building the entity IS the validation: X3, X4, and every bound are applied here
            # rather than restated, and the identity it carries is the row's.
            habit = declaration.as_habit(uuid4())
        created = await self._habits.create(
            area_id=declaration.area_id,
            title=declaration.title,
            habit=habit,
            created_at=now,
        )
        # The habit's TITLE is deliberately absent from this line. It is user-authored content,
        # and a habit titled "Therapy" discloses as much as a block title does.
        _log.info(
            "habits.habit.declared",
            tenant_id=str(principal.tenant_id),
            habit_id=str(created.id),
            area_id=str(created.area_id),
            cadence_kind=created.cadence_kind.value,
            binding_source=created.binding_source.value,
            miss_policy=created.miss_policy.value,
            variant_count=len(created.variants),
        )
        await self._request_solves_after(now)
        return (await self._read_all((created,)))[0]

    @measured("habits")
    async def update(
        self, principal: Principal, habit_id: HabitId, change: HabitChange
    ) -> ReadHabit:
        """Apply a partial update, and leave every recorded past occurrence untouched.

        Editing a habit changes future occurrences only. Nothing here writes to the outcome log,
        and an outcome carries its binding denormalized, so a week that already happened reads
        as it did whatever this changes.
        """
        require_scope(principal, Scope.ADMIN)
        now = self._clock()
        merged = change.applied_to(await self._require_habit(principal, habit_id))
        with stated_rejection():
            # The merged pair is what X3 and X4 are applied to, which is why a `PATCH` naming
            # only a binding source is refused when the stored variants contradict it.
            habit = merged.as_habit()
        await self._habits.write(habit, title=merged.title)
        _log.info(
            "habits.habit.changed",
            tenant_id=str(principal.tenant_id),
            habit_id=str(habit_id),
            cadence_kind=merged.cadence_kind.value,
            binding_source=merged.binding_source.value,
            miss_policy=merged.miss_policy.value,
            variant_count=len(merged.variants),
        )
        await self._request_solves_after(now)
        return (await self._read_all((merged,)))[0]

    @measured("habits")
    async def remove(self, principal: Principal, habit_id: HabitId) -> None:
        """Remove a habit. Its recorded outcomes stay, because they are facts about weeks."""
        require_scope(principal, Scope.ADMIN)
        now = self._clock()
        found = await self._require_habit(principal, habit_id)
        await self._habits.remove(found.id)
        _log.info(
            "habits.habit.removed",
            tenant_id=str(principal.tenant_id),
            habit_id=str(habit_id),
            area_id=str(found.area_id),
        )
        await self._request_solves_after(now)

    async def _request_solves_after(self, now: datetime) -> None:
        await self._bump.from_the_week_holding(now)
        await self._solve_requests.request(frozenset(await self._horizon.weeks_at(now)))

    async def _read_all(self, habits: Sequence[HabitRecord]) -> tuple[ReadHabit, ...]:
        """Each habit with its cursor and its debt.

        The log is read only when a habit rotates, because the cursor is the one figure left that
        derives here: a tenant whose habits all bind fixed content answers both figures without
        touching ``block_outcomes`` at all. Debt comes off the rows' stored charge, so it never
        widens the read.
        """
        if not habits:
            return ()
        rotating = [record.id for record in habits if record.as_habit().rotates]
        log = await self._outcomes.read(rotating) if rotating else ()
        return tuple(self._read_one(record, log) for record in habits)

    def _read_one(self, record: HabitRecord, log: Sequence[HabitOutcome]) -> ReadHabit:
        with stated_rejection():
            habit = record.as_habit()
        return ReadHabit(
            habit=record,
            cursor=cursor_reading(habit, log),
            debt=stored_reading(habit, record.charged_misses),
        )

    async def _require_habit(self, principal: Principal, habit_id: HabitId) -> HabitRecord:
        found = await self._habits.find(habit_id)
        if found is None:
            raise NotFound(f"No {HABIT_RESOURCE} matches that identifier.")
        authorize_tenant(principal, found.tenant_id, resource=HABIT_RESOURCE)
        return found
