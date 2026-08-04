"""The identifier aliases every scoped entity is keyed or scoped by.

They live in the pure package because the entities that carry them do: a tenant id
appears on every domain entity, and a user id appears on exactly one authentication
row, so both names are needed wherever those shapes are written rather than only
where they are persisted.

These are aliases, not distinct types: a ``TenantId`` and a ``UserId`` are both
UUIDs and mypy will not stop one being passed where the other is expected. What they
buy is a signature that says which identifier it wants.
"""

from __future__ import annotations

from uuid import UUID

type TenantId = UUID
type UserId = UUID
type PlanRevisionId = UUID
type OperationId = UUID
type AreaId = UUID
type ProjectId = UUID
type PreferenceId = UUID
type HabitId = UUID
type DayTypeId = UUID
type TemplateId = UUID
type TemplateEntryId = UUID
type OffPlanPeriodId = UUID
type TaskId = UUID
