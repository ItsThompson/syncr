"""What a request asked to declare or change, as the service takes it.

These sit between the route that read the request and the service that applies it, so the
service never imports a wire schema and the route never decides anything.

Every field of a change is three-valued: absent leaves the stored value alone, a value
replaces it, and null clears it where the column is nullable. That is
the explicit-null convention, and it is why a floor can be removed at all.

Neither change carries a parent or an Area. An Area's place in the hierarchy and a Project's
Area are declared once: the hours already spent were attributed to the Area the row was
declared in, so moving it would rewrite reported history.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from syncr_api.core.patches import Absent, resolved

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal

    from syncr_api.areas.records import AreaRecord, ProjectRecord
    from syncr_api.core.patches import Patched
    from syncr_domain.identifiers import AreaId
    from syncr_domain.pigments import PigmentIndex
    from syncr_domain.projects import ProjectStatus


@dataclass(frozen=True, slots=True)
class AreaDeclaration:
    """One Area to declare. The pigment is absent, because the deal assigns it."""

    name: str
    parent_id: AreaId | None
    budget_percent: Decimal | None
    floor_hours: Decimal | None


@dataclass(frozen=True, slots=True)
class AreaChange:
    """What one ``PATCH`` asked to change on an Area."""

    name: Patched[str]
    pigment_index: Patched[PigmentIndex]
    budget_percent: Patched[Decimal | None]
    floor_hours: Patched[Decimal | None]

    def changes_a_solve_input(self) -> bool:
        """Whether this change touches a value the solver or the probe reads.

        A name and a pigment step are read by the interface alone, so renaming an Area must
        not invalidate a running solve.
        """
        stated_a_budget = not isinstance(self.budget_percent, Absent)
        stated_a_floor = not isinstance(self.floor_hours, Absent)
        return stated_a_budget or stated_a_floor

    def applied_to(self, current: AreaRecord) -> AreaRecord:
        """``current`` with every field this change stated replaced."""
        return replace(
            current,
            name=resolved(self.name, current.name),
            pigment_index=resolved(self.pigment_index, current.pigment_index),
            budget_percent=resolved(self.budget_percent, current.budget_percent),
            floor_hours=resolved(self.floor_hours, current.floor_hours),
        )


@dataclass(frozen=True, slots=True)
class ProjectDeclaration:
    """One Project to declare. No budget fields: the Area carries the allocation."""

    area_id: AreaId
    name: str
    deadline: datetime | None
    status: ProjectStatus


@dataclass(frozen=True, slots=True)
class ProjectChange:
    """What one ``PATCH`` asked to change on a Project. Completing it is a status change."""

    name: Patched[str]
    deadline: Patched[datetime | None]
    status: Patched[ProjectStatus]

    def applied_to(self, current: ProjectRecord) -> ProjectRecord:
        """``current`` with every field this change stated replaced.

        The Area is carried through untouched, which is what leaves a completed Project's
        historical time attribution intact.
        """
        return replace(
            current,
            name=resolved(self.name, current.name),
            deadline=resolved(self.deadline, current.deadline),
            status=resolved(self.status, current.status),
        )
