"""The preference service: authorization, the entity's invariants, the chain, and the bump.

Five rules live here rather than anywhere else.

**A preference is validated by building the entity.** Which owner may carry a daily cap, what a
window is, and what an ideal duration may be are stated once in ``syncr_domain.preferences`` and
applied by constructing a ``Preference`` from the declaration before anything is written. A rule
restated in a request schema would be a second, weaker statement of this one.

**An owner has to exist, and that is the only thing these routes 404 on.** A missing preference is
an answer rather than an absence: the owner's Area may declare one, or nothing may be in effect at
all, and both are states a caller reads.

**The chain is one link for an Area and two for an override.** An Area is the root: there is
nothing above it to fall back to, so its own preference is what is in effect. An override's chain
is its own preference then its Area's, resolved by :func:`~syncr_domain.preferences.
preference_in_effect`, which returns one of them entire rather than merging two.

**A mutation bumps the week input version only when it changed something a solve reads.** A
replacement that stores what was already stored, and a removal of a preference nothing declared,
invalidate no solve: there is nothing new for one to re-read. The range is OPEN-ENDED, because a
preference has no end date and governs every week the user has not yet lived, so it is
``BacklogWideBump``'s range rather than a bounded one. A stored row this service cannot read counts
as a change, because nothing is equal to it, and that is also what keeps a replacement able to
repair one.

**Nothing here writes a cap onto an override, and there is no argument list that could.** A
declaration built from an override's request shape names ``None``, the entity refuses anything
else, and the table's own constraint refuses a row carrying one. The cap reaches the solver as the
Area budget's ``max_per_day_minutes`` rather than through the resolved preference, which is what
makes "an override cannot relax a hard cap" structural rather than remembered.

``authorize_tenant`` is called on the owner row a caller addresses by identifier. Every row these
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

from syncr_api.core.principal import authorize_tenant, require_scope
from syncr_api.core.scopes import Scope
from syncr_api.preferences.config import PREFERENCE_RESOURCE
from syncr_api.preferences.rules import stated_rejection, unknown_owner
from syncr_common.logging import get_logger
from syncr_common.metrics import measured
from syncr_domain.preferences import PreferenceError, preference_in_effect

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from syncr_api.core.clock import Clock
    from syncr_api.core.principal import Principal
    from syncr_api.preferences.declarations import PreferenceDeclaration
    from syncr_api.preferences.owners import PreferenceOwners, ResolvedOwner
    from syncr_api.preferences.records import PreferenceRecord
    from syncr_api.preferences.repository import PreferenceRepository
    from syncr_api.user_settings.solve_inputs import BacklogWideBump
    from syncr_domain.preferences import Preference, PreferenceOwner, PreferenceOwnerKind

_log = get_logger("syncr.preferences")


@dataclass(frozen=True, slots=True)
class ReadPreference:
    """What one owner declares, and what is actually in effect for it.

    Both are read in the same call over the same rows, so a response cannot show a declaration
    from one read and an effective preference resolved against another.

    ``in_effect`` is the owner's own when it declared one, its Area's when it did not, and ``None``
    when neither did. Where it came from is ``in_effect.owner``, so there is no second field for a
    source that could disagree with it.
    """

    owner: PreferenceOwner
    declared: Preference | None
    in_effect: Preference | None


class PreferenceService:
    """Reads, replaces, and removes the preference on one Area, Habit, or Task."""

    def __init__(
        self,
        preferences: PreferenceRepository,
        owners: PreferenceOwners,
        bump: BacklogWideBump,
        clock: Clock,
    ) -> None:
        self._preferences = preferences
        self._owners = owners
        self._bump = bump
        self._clock = clock

    @measured("preferences")
    async def read(
        self, principal: Principal, kind: PreferenceOwnerKind, owner_id: UUID
    ) -> ReadPreference:
        """What this owner declares and what is in effect for it, or a 404 for an unknown owner."""
        require_scope(principal, Scope.PLAN_READ)
        return await self._read(await self._require_owner(principal, kind, owner_id))

    @measured("preferences")
    async def replace(
        self,
        principal: Principal,
        kind: PreferenceOwnerKind,
        owner_id: UUID,
        declaration: PreferenceDeclaration,
    ) -> ReadPreference:
        """Replace this owner's preference whole, and invalidate the weeks a solve could re-read.

        Whole rather than field by field: the stored row is overwritten by the declaration, so a
        field the request left out is null afterwards even when the previous row held a value.
        That is the contract the ``PUT`` states.
        """
        require_scope(principal, Scope.ADMIN)
        now = self._clock()
        resolved = await self._require_owner(principal, kind, owner_id)
        stored = await self._preferences.find(resolved.owner)
        # Read OUTSIDE the context below, deliberately. See the helper: a stored row this service
        # cannot read must not refuse a replacement that would repair it.
        was = _the_preference_being_replaced(stored)
        with stated_rejection():
            # Building the entity IS the validation: the cap's owner rule and every bound are
            # applied here rather than restated.
            declared = declaration.as_preference(resolved.owner)
        if stored is None:
            await self._preferences.create(declared, created_at=now)
        else:
            await self._preferences.write(declared)
        _log.info(
            "preferences.preference.replaced",
            tenant_id=str(principal.tenant_id),
            owner_kind=resolved.owner.kind.value,
            owner_id=str(resolved.owner.id),
            # The windows themselves are the user's own routine: a line carrying 05:30 discloses
            # when they get up. The count is what a reader of the log needs.
            window_count=len(declared.windows),
            strength=declared.strength.value,
            has_preferred_duration=declared.preferred_duration_minutes is not None,
            has_max_per_day=declared.max_per_day_minutes is not None,
            created=stored is None,
            # So an operator can see that a row nothing could read was overwritten, which is the
            # one case where a replacement discards a value rather than superseding it.
            repaired_unreadable=stored is not None and was is None,
        )
        await self._invalidate_if_changed(was=was, now_is=declared, at=now)
        return await self._read(resolved)

    @measured("preferences")
    async def remove(
        self, principal: Principal, kind: PreferenceOwnerKind, owner_id: UUID
    ) -> ReadPreference:
        """Remove this owner's preference, restoring whatever its Area declares.

        Answers what is in effect afterwards, which for an override is its Area's preference. An
        owner that declared none is left as it was: the caller asked for the state it is already
        in, so nothing is written and nothing is invalidated.
        """
        require_scope(principal, Scope.ADMIN)
        now = self._clock()
        resolved = await self._require_owner(principal, kind, owner_id)
        removed = await self._preferences.remove(resolved.owner)
        _log.info(
            "preferences.preference.removed",
            tenant_id=str(principal.tenant_id),
            owner_kind=resolved.owner.kind.value,
            owner_id=str(resolved.owner.id),
            rows_removed=removed,
        )
        if removed:
            await self._bump.from_the_week_holding(now)
        return await self._read(resolved)

    async def _require_owner(
        self, principal: Principal, kind: PreferenceOwnerKind, owner_id: UUID
    ) -> ResolvedOwner:
        found = await self._owners.find(kind, owner_id)
        if found is None:
            raise unknown_owner(kind)
        authorize_tenant(principal, found.tenant_id, resource=PREFERENCE_RESOURCE)
        return found

    async def _read(self, resolved: ResolvedOwner) -> ReadPreference:
        declared = await self._preferences.find(resolved.owner)
        with stated_rejection():
            chain = await self._chain(resolved, declared)
            return ReadPreference(
                owner=resolved.owner,
                declared=_as_entity(declared),
                in_effect=preference_in_effect(*chain),
            )

    async def _chain(
        self, resolved: ResolvedOwner, declared: PreferenceRecord | None
    ) -> tuple[Preference | None, ...]:
        """The preferences that could apply, most specific first.

        One link for an Area, because an Area is the root: nothing sits above it, and reading its
        own row a second time would put an Area's preference ahead of itself, which the resolution
        refuses for the reason it exists.
        """
        if resolved.owner.is_an_area:
            return (_as_entity(declared),)
        area = await self._preferences.find(resolved.area_owner)
        return (_as_entity(declared), _as_entity(area))

    async def _invalidate_if_changed(
        self, *, was: Preference | None, now_is: Preference, at: datetime
    ) -> None:
        """Bump the open-ended week range, unless the replacement stored what was already there.

        Window order cannot make this fire on its own: the entity canonicalizes its windows, so a
        request that only reorders them is equal to what was stored.
        """
        if was == now_is:
            return
        await self._bump.from_the_week_holding(at)


def _as_entity(record: PreferenceRecord | None) -> Preference | None:
    return record.as_preference() if record is not None else None


def _the_preference_being_replaced(stored: PreferenceRecord | None) -> Preference | None:
    """The row a replacement is about to overwrite, or ``None`` when nothing readable is there.

    This value exists only to answer whether the replacement changes anything, so a row this
    service cannot read is reported as absent: nothing is equal to it, which is what the gate
    needs, and a replacement carrying a valid body then goes through.

    Reading it inside the context that maps a domain refusal to a 422 would mean an unreadable
    STORED row refused a request that had nothing wrong with it, leaving removal as the only way
    to clear it. A row can only get into that state by being written around the application, but
    a repair path that a broken row can close is a worse failure than the broken row.
    """
    if stored is None:
        return None
    try:
        return stored.as_preference()
    except PreferenceError:
        return None
