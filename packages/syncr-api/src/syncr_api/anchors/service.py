"""The anchor services: what a route may ask, and the rules each answer is subject to.

Two services in one module, because there are two subjects and because the authorization boundary
test discovers a service class by walking ``*/service.py``: a service kept elsewhere would fall
outside the rule that every public method takes a principal first. The value shapes they return
live in ``views.py`` and the rules they apply live in ``rules.py``, so what is here is the
ordering of reads and writes and nothing else.

**An anchor is read-only, and that is a property of this surface.** There is no ``update``, no
``remove``, and no way to reach a title, an interval, or a location through either service.
:meth:`AnchorService.retype` changes ``anchor_type_id`` and nothing else, which changes what the
commitment RESERVES around itself rather than the commitment.

**A retype persists on the series.** Retyping one occurrence of a recurring meeting is a
statement about the meeting, so a daily standup is typed once rather than 250 times. An
occurrence with no series is retyped alone, which is the same rule with a series of one.

**Every anchor-type mutation invalidates a solve.** A type declares the prep, transit, and
recovery every anchor of it casts, so creating, editing, removing, or reordering one regenerates
shadows, which are solve inputs. The bump runs from the current week onwards: a type governs
every week the user has not yet lived, and a past week's approved revision keeps the inputs it
was computed with.

**A retype bumps the same range, and that is an over-approximation stated rather than hidden.**
The narrow answer would be the weeks the retyped occurrences and their shadows fall in, which
needs geometry this module does not own. A series retype reaches arbitrary future weeks, so the
wide range is right for the case that matters and costs a solve of weeks whose inputs did not
move for the case that does not.

``authorize_tenant`` is called on the one row a caller addresses by identifier. Every row these
methods touch came from a repository scoped to the principal's own tenant, so the scoped
``SELECT`` is what turns another tenant's identifier into a 404; the explicit call is defense in
depth, at the only place an unscoped read could be introduced.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.anchors import rules
from syncr_api.anchors.config import ANCHOR_RESOURCE, ANCHOR_TYPE_RESOURCE
from syncr_api.anchors.views import AnchorPage, Retyped, anchor_view, anchor_views
from syncr_api.core.errors import FieldError, NotFound, ValidationFailed
from syncr_api.core.principal import authorize_tenant, require_scope
from syncr_api.core.scopes import Scope
from syncr_api.user_settings.solve_inputs import weeks_from
from syncr_api.user_settings.zone_reading import local_date
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.anchors.declarations import AnchorTypeChange, RuleOrder, TypeAssignment
    from syncr_api.anchors.evaluation import RuleEvaluator
    from syncr_api.anchors.records import (
        AnchorId,
        AnchorRecord,
        AnchorTypeId,
        AnchorTypeRecord,
        AnchorTypeSpecification,
    )
    from syncr_api.anchors.repository import AnchorRepository
    from syncr_api.anchors.type_repository import AnchorTypeRepository
    from syncr_api.anchors.views import AnchorView
    from syncr_api.areas.repository import AreaRepository
    from syncr_api.calendars.repository import CalendarSourceRepository
    from syncr_api.core.clock import Clock
    from syncr_api.core.principal import Principal
    from syncr_api.user_settings.repository import SettingsRepository
    from syncr_api.user_settings.solve_inputs import WeekInputVersions
    from syncr_domain.intervals import Interval

_log = get_logger("syncr.anchors")


class AnchorService:
    """Read one tenant's anchors, and retype one. Nothing here can change an imported fact."""

    def __init__(
        self,
        anchors: AnchorRepository,
        types: AnchorTypeRepository,
        sources: CalendarSourceRepository,
        settings: SettingsRepository,
        versions: WeekInputVersions,
        clock: Clock,
    ) -> None:
        self._anchors = anchors
        self._types = types
        self._sources = sources
        self._settings = settings
        self._versions = versions
        self._clock = clock

    @measured("anchors")
    async def list_in_span(
        self,
        principal: Principal,
        span: Interval,
        *,
        limit: int,
        after: tuple[datetime, AnchorId] | None = None,
    ) -> AnchorPage:
        """The anchors overlapping ``span``, earliest first, one page at a time. Writes nothing.

        Three reads whatever the page holds: the page itself, the tenant's sources, and its types.
        One more row than the page holds is read, so "is there another page" is answered by the
        read rather than by a second count that could disagree with it.
        """
        require_scope(principal, Scope.PLAN_READ)
        found = await self._anchors.in_span(span, limit=limit + 1, after=after)
        page = found[:limit]
        composed = anchor_views(
            page, sources=await self._sources.list_all(), types=await self._types.list_all()
        )
        if len(found) <= limit:
            return AnchorPage(views=composed, next_cursor=None)
        last = page[-1]
        return AnchorPage(views=composed, next_cursor=(last.interval.start, last.id))

    @measured("anchors")
    async def read(self, principal: Principal, anchor_id: AnchorId) -> AnchorView:
        """One anchor, with its source named and its read-only status stated. Writes nothing."""
        require_scope(principal, Scope.PLAN_READ)
        return await self._viewed(await self._found(principal, anchor_id))

    @measured("anchors")
    async def retype(
        self, principal: Principal, anchor_id: AnchorId, assignment: TypeAssignment
    ) -> Retyped:
        """Retype one occurrence, persisting on its series, and invalidate the weeks it governs.

        The override is set whichever type was chosen, including no type at all: "this standup is
        not an interview" is a decision, and a later rule match must not undo it.
        """
        require_scope(principal, Scope.PLAN_WRITE)
        now = self._clock()
        found = await self._found(principal, anchor_id)
        await self._require_declared_type(assignment.anchor_type_id)
        moved = await self._retyped(found, assignment)

        _log.info(
            "anchors.anchor.retyped",
            tenant_id=str(principal.tenant_id),
            anchor_id=str(anchor_id),
            anchor_type_id=str(assignment.anchor_type_id),
            on_a_series=found.series_uid is not None,
            occurrences_retyped=moved,
        )
        settings = await self._settings.read()
        await self._versions.bump(weeks_from(local_date(now, settings.home_zone)))
        return Retyped(
            view=await self._viewed(await self._found(principal, anchor_id)),
            occurrences_retyped=moved,
        )

    async def _retyped(self, found: AnchorRecord, assignment: TypeAssignment) -> int:
        if found.series_uid is None:
            return await self._anchors.retype_one(
                found.id, anchor_type_id=assignment.anchor_type_id
            )
        return await self._anchors.retype_series(
            source_id=found.source_id,
            series_uid=found.series_uid,
            anchor_type_id=assignment.anchor_type_id,
        )

    async def _found(self, principal: Principal, anchor_id: AnchorId) -> AnchorRecord:
        found = await self._anchors.find(anchor_id)
        if found is None:
            raise NotFound(f"No {ANCHOR_RESOURCE} matches that identifier.")
        authorize_tenant(principal, found.tenant_id, resource=ANCHOR_RESOURCE)
        return found

    async def _viewed(self, anchor: AnchorRecord) -> AnchorView:
        anchor_type = (
            None if anchor.anchor_type_id is None else await self._types.find(anchor.anchor_type_id)
        )
        return anchor_view(
            anchor,
            source=await self._sources.find(anchor.source_id),
            anchor_type=anchor_type,
        )

    async def _require_declared_type(self, anchor_type_id: AnchorTypeId | None) -> None:
        if anchor_type_id is None or await self._types.find(anchor_type_id) is not None:
            return
        raise ValidationFailed(
            f"No {ANCHOR_TYPE_RESOURCE} matches that identifier, so this commitment was not "
            "retyped. Nothing was changed and it still reserves whatever it reserved before. "
            "Declare the anchor type first, or send a null type to leave this commitment as "
            "opaque busy time.",
            errors=[
                FieldError(
                    field="anchorTypeId",
                    message=f"No {ANCHOR_TYPE_RESOURCE} matches that identifier.",
                )
            ],
        )


class AnchorTypeService:
    """Declare, edit, reorder, and remove the rules that type one tenant's anchors."""

    def __init__(
        self,
        types: AnchorTypeRepository,
        anchors: AnchorRepository,
        areas: AreaRepository,
        sources: CalendarSourceRepository,
        evaluator: RuleEvaluator,
        settings: SettingsRepository,
        versions: WeekInputVersions,
        clock: Clock,
    ) -> None:
        self._types = types
        self._anchors = anchors
        self._areas = areas
        self._sources = sources
        self._evaluator = evaluator
        self._settings = settings
        self._versions = versions
        self._clock = clock

    @measured("anchors")
    async def list_all(self, principal: Principal) -> tuple[AnchorTypeRecord, ...]:
        """Every type this tenant declares, in evaluation order. Writes nothing."""
        require_scope(principal, Scope.PLAN_READ)
        return await self._types.list_all()

    @measured("anchors")
    async def read(self, principal: Principal, anchor_type_id: AnchorTypeId) -> AnchorTypeRecord:
        """One type of this tenant's. Writes nothing."""
        require_scope(principal, Scope.PLAN_READ)
        return await self._found(principal, anchor_type_id)

    @measured("anchors")
    async def create(
        self, principal: Principal, specification: AnchorTypeSpecification
    ) -> AnchorTypeRecord:
        """Declare a type at the end of the evaluation order, and type what it now matches.

        Appended rather than inserted, because a new rule must not silently outrank rules the
        user already ordered. Reorder it afterwards if it belongs earlier.
        """
        require_scope(principal, Scope.ADMIN)
        now = self._clock()
        existing = await self._types.lock_all()
        rules.require_room_for_another_type(existing)
        rules.require_an_unused_name(specification.name, existing)
        await self._validate(specification)

        created = await self._types.create(
            rule_order=len(existing), specification=specification, created_at=now
        )
        _log.info(
            "anchors.type.declared",
            tenant_id=str(principal.tenant_id),
            anchor_type_id=str(created.id),
            rule_order=created.rule_order,
            post_scope=created.specification.post_scope,
        )
        await self._settle(now)
        return created

    @measured("anchors")
    async def update(
        self, principal: Principal, anchor_type_id: AnchorTypeId, change: AnchorTypeChange
    ) -> AnchorTypeRecord:
        """Apply a partial update, rejecting a geometry that cannot be laid out.

        The change is merged onto the stored specification and the merged value is what the
        boundary rules see, so an edit that lowers a prep lead and an edit that raises a transit
        duration are caught as the same collision.
        """
        require_scope(principal, Scope.ADMIN)
        now = self._clock()
        existing = await self._types.lock_all()
        current = next((row for row in existing if row.id == anchor_type_id), None)
        if current is None:
            raise NotFound(f"No {ANCHOR_TYPE_RESOURCE} matches that identifier.")
        authorize_tenant(principal, current.tenant_id, resource=ANCHOR_TYPE_RESOURCE)

        merged = change.applied_to(current.specification)
        rules.require_an_unused_name(merged.name, existing, apart_from=anchor_type_id)
        await self._validate(merged)

        await self._types.write(anchor_type_id, merged)
        _log.info(
            "anchors.type.changed",
            tenant_id=str(principal.tenant_id),
            anchor_type_id=str(anchor_type_id),
            match_rule_changed=change.changes_a_match_rule(),
        )
        await self._settle(now)
        return await self._found(principal, anchor_type_id)

    @measured("anchors")
    async def remove(self, principal: Principal, anchor_type_id: AnchorTypeId) -> None:
        """Remove a type, release the anchors holding it, and let the rules claim them again.

        The override flag is released with the identifier. An override naming a type nobody can
        name any more is a state no route could leave, so removing the type returns its anchors
        to rule matching rather than freezing them untyped.
        """
        require_scope(principal, Scope.ADMIN)
        now = self._clock()
        await self._found(principal, anchor_type_id)
        released = await self._anchors.release_type(anchor_type_id)
        await self._types.remove(anchor_type_id)
        _log.info(
            "anchors.type.removed",
            tenant_id=str(principal.tenant_id),
            anchor_type_id=str(anchor_type_id),
            anchors_released=released,
        )
        await self._settle(now)

    @measured("anchors")
    async def reorder(self, principal: Principal, order: RuleOrder) -> tuple[AnchorTypeRecord, ...]:
        """Rewrite the evaluation order, and re-evaluate every anchor a rule may still type.

        The whole order or nothing. A partial order would leave the unnamed types at positions the
        caller could not see, and first-match semantics make that a silent change to what every
        one of them matches.
        """
        require_scope(principal, Scope.ADMIN)
        now = self._clock()
        existing = await self._types.lock_all()
        rules.require_a_total_order(order.anchor_type_ids, existing)

        for position, anchor_type_id in enumerate(order.anchor_type_ids):
            await self._types.set_rule_order(anchor_type_id, rule_order=position)
        _log.info(
            "anchors.types.reordered",
            tenant_id=str(principal.tenant_id),
            rule_count=len(order.anchor_type_ids),
        )
        await self._settle(now)
        return await self._types.list_all()

    async def _found(self, principal: Principal, anchor_type_id: AnchorTypeId) -> AnchorTypeRecord:
        found = await self._types.find(anchor_type_id)
        if found is None:
            raise NotFound(f"No {ANCHOR_TYPE_RESOURCE} matches that identifier.")
        authorize_tenant(principal, found.tenant_id, resource=ANCHOR_TYPE_RESOURCE)
        return found

    async def _validate(self, specification: AnchorTypeSpecification) -> None:
        """Every boundary rule, against the Areas and sources this tenant actually holds.

        Each read is skipped when the specification names nothing that needs it, so a type with
        no Areas and no source rule costs no extra query.
        """
        declared_areas = (
            {area.id for area in await self._areas.list_all()}
            if specification.referenced_area_ids
            else frozenset()
        )
        declared_sources = (
            {source.id for source in await self._sources.list_all()}
            if specification.match_source_id is not None
            else frozenset()
        )
        rules.validate(
            specification, declared_areas=declared_areas, declared_sources=declared_sources
        )

    async def _settle(self, now: datetime) -> None:
        """Re-type what the rules now claim, and invalidate the weeks the change governs.

        One method because the two always happen together: a rule-set edit changes which anchors
        are typed AND what each of them casts, and a solve that read the old answer has to be
        superseded either way.
        """
        await self._evaluator.re_evaluate()
        settings = await self._settings.read()
        await self._versions.bump(weeks_from(local_date(now, settings.home_zone)))
