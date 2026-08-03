"""The immutable views of an Area row and a Project row.

A repository hands back one of these rather than a mapped instance, so a service cannot
trigger a load it did not ask for, a fake repository in a service test is a function
returning a frozen dataclass, and nothing downstream can change a row by assigning to it.

These are not the wire shapes: ``schemas.py`` owns those, so a column added here does not
appear in a response by itself. They are not the arithmetic's shapes either:
``syncr_domain.budgets.AreaShare`` is what the budget report is stated over, and
:meth:`AreaRecord.as_share` is where the two meet.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from syncr_domain.budgets import AreaShare, floor_minutes

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_domain.identifiers import AreaId, PreferenceId, ProjectId, TenantId
    from syncr_domain.pigments import PigmentIndex
    from syncr_domain.projects import ProjectStatus

# What an Area with no declared share contributes to the proportional remainder.
_NO_SHARE = Decimal(0)


@dataclass(frozen=True, slots=True)
class AreaRecord:
    """One Area, as persistence knows it."""

    id: AreaId
    tenant_id: TenantId
    parent_id: AreaId | None
    name: str
    pigment_index: PigmentIndex
    budget_percent: Decimal | None
    floor_hours: Decimal | None
    default_preference_id: PreferenceId | None
    created_at: datetime

    def as_share(self) -> AreaShare:
        """The declaration the budget report divides discretionary time by.

        An undeclared share and an undeclared floor both reach the arithmetic as nothing,
        which is what makes an Area with no budget contribute a zero target rather than an
        absent one: it still holds time, and the report still has a row for it.
        """
        return AreaShare(
            area_id=self.id,
            parent_id=self.parent_id,
            floor_minutes=floor_minutes(self.floor_hours),
            budget_percent=_NO_SHARE if self.budget_percent is None else self.budget_percent,
        )


@dataclass(frozen=True, slots=True)
class ProjectRecord:
    """One Project, as persistence knows it. No budget fields, by design."""

    id: ProjectId
    tenant_id: TenantId
    area_id: AreaId
    name: str
    deadline: datetime | None
    status: ProjectStatus
    created_at: datetime
