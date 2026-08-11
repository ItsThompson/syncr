"""The three day-shape services: authorization, the ordering of reads and writes, and the bump.

What is decided here is which read happens before which write. The rules those reads feed are
stated in :mod:`syncr_api.templates.rules`, because each is an invariant over rows the tenant
already holds rather than a step in a request.

**An entry is addressed through the shape that holds it.** Both identifiers in the path are
used: the shape is read first and the entry is found among its own, so an entry of another shape
is a 404 rather than an edit through the wrong path.

**Which weeks a mutation invalidates is one rule, in one place.** ``FutureWeeks`` owns it and the
pattern's own ``covers`` is what decides, so nothing here compares a day type against a mapping.
Every mutation states in its log line whether it reached a week.

**Two of those reads refuse what a unique index also refuses.** A day type's name and a day
type's one shape are each read before the write and guaranteed by an index, so both writes go
through :func:`syncr_api.core.races.answered_once` and a caller that passed the read at the same
moment as another is answered by that read rather than by a fault.

``authorize_tenant`` is called on the one row a caller addresses by identifier. Every row these
methods touch came from a repository scoped to the principal's own tenant, so the scoped
``SELECT`` is what turns another tenant's identifier into a 404; the explicit call is defense in
depth, at the only place an unscoped read could be introduced.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from syncr_api.core.errors import NotFound
from syncr_api.core.principal import authorize_tenant, require_scope
from syncr_api.core.races import answered_once
from syncr_api.core.scopes import Scope
from syncr_api.templates.config import (
    ONE_DAY_TYPE_PER_NAME_INDEX,
    ONE_SHAPE_PER_DAY_TYPE_INDEX,
    TEMPLATE_ENTRY_RESOURCE,
    TEMPLATE_RESOURCE,
    WEEK_PATTERN_RESOURCE,
)
from syncr_api.templates.rules import (
    find_entry,
    require_a_declared_area,
    require_a_declared_day_type,
    require_an_unshaped_day_type,
    require_an_unused_day_type_name,
    stated_rejection,
)
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from syncr_api.areas.repository import AreaRepository
    from syncr_api.core.clock import Clock
    from syncr_api.core.principal import Principal
    from syncr_api.core.races import Savepoint
    from syncr_api.templates.declarations import (
        DayTypeDeclaration,
        EntryChange,
        EntryDeclaration,
        TemplateChange,
        TemplateDeclaration,
    )
    from syncr_api.templates.invalidation import FutureWeeks
    from syncr_api.templates.records import DayTypeRecord, TemplateEntryRecord, TemplateRecord
    from syncr_api.templates.repository import (
        DayTypeRepository,
        TemplateRepository,
        WeekPatternRepository,
    )
    from syncr_domain.identifiers import TemplateEntryId, TemplateId
    from syncr_domain.templates import WeekPattern

_log = get_logger("syncr.templates")


class DayTypeService:
    """Read and declare one tenant's day types.

    Declaring one invalidates nothing. A day type no weekday maps and no shape describes cannot
    change what a week materializes.
    """

    def __init__(self, day_types: DayTypeRepository, clock: Clock, savepoint: Savepoint) -> None:
        self._day_types = day_types
        self._clock = clock
        self._savepoint = savepoint

    @measured("templates")
    async def list_all(self, principal: Principal) -> tuple[DayTypeRecord, ...]:
        """Every day type, in the order they were declared. Writes nothing."""
        require_scope(principal, Scope.PLAN_READ)
        return await self._day_types.list_all()

    @measured("templates")
    async def create(self, principal: Principal, declaration: DayTypeDeclaration) -> DayTypeRecord:
        """Declare a day type, refusing a name another already holds.

        The name check is a courtesy that produces a stated 409 and the unique index is the
        guarantee, which is why the read holds no lock and the write carries the same check
        for the caller that passed it at the same moment as another.
        """
        require_scope(principal, Scope.ADMIN)

        async def require_a_free_name() -> None:
            require_an_unused_day_type_name(declaration.name, await self._day_types.list_all())

        await require_a_free_name()
        created = await answered_once(
            savepoint=self._savepoint,
            index=ONE_DAY_TYPE_PER_NAME_INDEX,
            write=lambda: self._day_types.create(name=declaration.name, created_at=self._clock()),
            refusal=require_a_free_name,
        )
        # The NAME is deliberately absent from this line. It is user-authored content, and a day
        # type named after a job discloses as much as a block title does.
        _log.info(
            "templates.day_type.declared",
            tenant_id=str(principal.tenant_id),
            day_type_id=str(created.id),
        )
        return created


class TemplateService:
    """Read and change one tenant's day shapes, and the entries that make them up."""

    def __init__(
        self,
        templates: TemplateRepository,
        day_types: DayTypeRepository,
        areas: AreaRepository,
        weeks: FutureWeeks,
        clock: Clock,
        savepoint: Savepoint,
    ) -> None:
        self._templates = templates
        self._day_types = day_types
        self._areas = areas
        self._weeks = weeks
        self._clock = clock
        self._savepoint = savepoint

    @measured("templates")
    async def list_all(self, principal: Principal) -> tuple[TemplateRecord, ...]:
        """Every shape with its entries, oldest first. Writes nothing."""
        require_scope(principal, Scope.PLAN_READ)
        return await self._templates.list_all()

    @measured("templates")
    async def read(self, principal: Principal, template_id: TemplateId) -> TemplateRecord:
        """One shape of this tenant's, with its entries in the order the day runs."""
        require_scope(principal, Scope.PLAN_READ)
        return await self._require_template(principal, template_id)

    @measured("templates")
    async def create(
        self, principal: Principal, declaration: TemplateDeclaration
    ) -> TemplateRecord:
        """Declare the shape of a day type that has none yet.

        The one-shape check is a courtesy that produces a stated 409 and the unique index is the
        guarantee, which is why the read holds no lock and the write carries the same check for
        the caller that passed it at the same moment as another.
        """
        require_scope(principal, Scope.ADMIN)
        require_a_declared_day_type(declaration.day_type_id, await self._day_types.list_all())

        async def require_an_unshaped_target() -> None:
            require_an_unshaped_day_type(
                await self._templates.find_by_day_type(declaration.day_type_id)
            )

        await require_an_unshaped_target()
        created = await answered_once(
            savepoint=self._savepoint,
            index=ONE_SHAPE_PER_DAY_TYPE_INDEX,
            write=lambda: self._templates.create(
                day_type_id=declaration.day_type_id,
                name=declaration.name,
                created_at=self._clock(),
            ),
            refusal=require_an_unshaped_target,
        )
        invalidated = await self._weeks.invalidate_if_mapped(created.day_type_id)
        _log.info(
            "templates.template.declared",
            tenant_id=str(principal.tenant_id),
            template_id=str(created.id),
            day_type_id=str(created.day_type_id),
            weeks_invalidated=invalidated,
        )
        return created

    @measured("templates")
    async def update(
        self, principal: Principal, template_id: TemplateId, change: TemplateChange
    ) -> TemplateRecord:
        """Rename a shape. Its day type and its entries are untouched."""
        require_scope(principal, Scope.ADMIN)
        current = await self._require_template(principal, template_id)
        merged = change.applied_to(current)
        await self._templates.write(template_id, name=merged.name)
        invalidated = await self._weeks.invalidate_if_mapped(merged.day_type_id)
        _log.info(
            "templates.template.changed",
            tenant_id=str(principal.tenant_id),
            template_id=str(template_id),
            weeks_invalidated=invalidated,
        )
        return merged

    @measured("templates")
    async def remove(self, principal: Principal, template_id: TemplateId) -> None:
        """Remove a shape and every entry in it."""
        require_scope(principal, Scope.ADMIN)
        current = await self._require_template(principal, template_id)
        await self._templates.remove(template_id)
        invalidated = await self._weeks.invalidate_if_mapped(current.day_type_id)
        _log.info(
            "templates.template.removed",
            tenant_id=str(principal.tenant_id),
            template_id=str(template_id),
            entries_removed=len(current.entries),
            weeks_invalidated=invalidated,
        )

    @measured("templates")
    async def add_entry(
        self, principal: Principal, template_id: TemplateId, declaration: EntryDeclaration
    ) -> TemplateEntryRecord:
        """Add one entry to a shape, after checking whatever Area it names.

        The span arrived already checked against the grid, because it is a domain shape: a
        request naming an off-grid time was refused before this method was reached.
        """
        require_scope(principal, Scope.ADMIN)
        shape = await self._require_template(principal, template_id)
        content = declaration.content()
        if content.area_id is not None:
            require_a_declared_area(await self._areas.find(content.area_id))
        created = await self._templates.create_entry(
            template_id=template_id, span=declaration.span, content=content
        )
        invalidated = await self._weeks.invalidate_if_mapped(shape.day_type_id)
        _log.info(
            "templates.entry.added",
            tenant_id=str(principal.tenant_id),
            template_id=str(template_id),
            entry_id=str(created.id),
            kind=created.kind.value,
            weeks_invalidated=invalidated,
        )
        return created

    @measured("templates")
    async def change_entry(
        self,
        principal: Principal,
        template_id: TemplateId,
        entry_id: TemplateEntryId,
        change: EntryChange,
    ) -> TemplateEntryRecord:
        """Move or resize one entry of a shape. What it holds is declared once.

        The merge is where a patched span is first expressible, so it is where the grid rule can
        refuse one: a patch moving an entry to 07:05 is a 422 naming the field, not a stored row.
        """
        require_scope(principal, Scope.ADMIN)
        shape = await self._require_template(principal, template_id)
        current = self._require_entry(entry_id, shape)
        with stated_rejection():
            merged = change.applied_to(current.span)
        await self._templates.write_entry(entry_id, span=merged)
        invalidated = await self._weeks.invalidate_if_mapped(shape.day_type_id)
        _log.info(
            "templates.entry.changed",
            tenant_id=str(principal.tenant_id),
            template_id=str(template_id),
            entry_id=str(entry_id),
            weeks_invalidated=invalidated,
        )
        return replace(current, span=merged)

    @measured("templates")
    async def remove_entry(
        self, principal: Principal, template_id: TemplateId, entry_id: TemplateEntryId
    ) -> None:
        """Remove one entry of a shape."""
        require_scope(principal, Scope.ADMIN)
        shape = await self._require_template(principal, template_id)
        self._require_entry(entry_id, shape)
        await self._templates.remove_entry(entry_id)
        invalidated = await self._weeks.invalidate_if_mapped(shape.day_type_id)
        _log.info(
            "templates.entry.removed",
            tenant_id=str(principal.tenant_id),
            template_id=str(template_id),
            entry_id=str(entry_id),
            weeks_invalidated=invalidated,
        )

    async def _require_template(
        self, principal: Principal, template_id: TemplateId
    ) -> TemplateRecord:
        found = await self._templates.find(template_id)
        if found is None:
            raise NotFound(f"No {TEMPLATE_RESOURCE} matches that identifier.")
        authorize_tenant(principal, found.tenant_id, resource=TEMPLATE_RESOURCE)
        return found

    def _require_entry(
        self, entry_id: TemplateEntryId, shape: TemplateRecord
    ) -> TemplateEntryRecord:
        found = find_entry(entry_id, shape.entries)
        if found is None:
            raise NotFound(f"No {TEMPLATE_ENTRY_RESOURCE} matches that identifier.")
        return found


class WeekPatternService:
    """Read and replace one tenant's weekday-to-day-type mapping."""

    def __init__(
        self,
        patterns: WeekPatternRepository,
        day_types: DayTypeRepository,
        weeks: FutureWeeks,
    ) -> None:
        self._patterns = patterns
        self._day_types = day_types
        self._weeks = weeks

    @measured("templates")
    async def read(self, principal: Principal) -> WeekPattern:
        """The pattern, or a 404 stating that none has been declared."""
        require_scope(principal, Scope.PLAN_READ)
        found = await self._patterns.read()
        if found is None:
            raise NotFound(
                f"No {WEEK_PATTERN_RESOURCE} has been declared. Declare all seven weekdays at "
                "once: a pattern is replaced whole rather than patched, because a day with no "
                "day type would materialize nothing at all."
            )
        return found

    @measured("templates")
    async def replace(self, principal: Principal, pattern: WeekPattern) -> WeekPattern:
        """Replace the whole mapping, and invalidate every future week.

        Every future week, without asking whether anything moved: the pattern maps all seven
        weekdays, so there is no future week it does not describe. Past weeks keep the inputs
        their approved revisions were computed with.
        """
        require_scope(principal, Scope.ADMIN)
        declared = await self._day_types.list_all()
        for day_type_id in dict.fromkeys(pattern.mapping.values()):
            require_a_declared_day_type(day_type_id, declared)
        await self._patterns.replace(pattern)
        await self._weeks.invalidate()
        _log.info(
            "templates.week_pattern.replaced",
            tenant_id=str(principal.tenant_id),
            day_types_used=len(set(pattern.mapping.values())),
        )
        return pattern
