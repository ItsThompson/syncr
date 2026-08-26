"""The immutable view of a habit row, and where it meets the domain shapes.

A repository hands one of these back rather than a mapped instance, so a service cannot trigger
a load it did not ask for, a fake repository in a service test is a function returning a frozen
dataclass, and nothing downstream can change a row by assigning to it.

This is not the wire shape: ``schemas.py`` owns that, so a column added to the table does not
appear in a response by sharing a name with a field.

:meth:`HabitRecord.as_habit` is where the row meets the entity the invariants and the two
derivations are stated over. It is a method rather than a stored field for the same reason
``TaskRecord.remaining_minutes`` is: the entity is a reading of the row, and storing a second
copy of one would be storing a value that can disagree with the row it came from.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.habits import (
    CadenceKind,
    Duration,
    EveryApproxDays,
    Habit,
    TimesPerWeek,
    build_cadence,
    cadence_kind,
)

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_domain.habits import BindingSource, Cadence, MissPolicy
    from syncr_domain.identifiers import AreaId, HabitId, TenantId


@dataclass(frozen=True, slots=True)
class HabitRecord:
    """One habit, as persistence knows it.

    The cadence arrives as its three columns rather than as a ``Cadence``, so a record is
    buildable from a row without the row having to construct a domain value first, and so a
    stored pair that disagrees with its discriminator is refused where it is read rather than
    where it was written.
    """

    id: HabitId
    tenant_id: TenantId
    area_id: AreaId
    title: str
    cadence_kind: CadenceKind
    cadence_times_per_week: int | None
    cadence_approx_days: int | None
    duration_min_minutes: int
    duration_max_minutes: int
    miss_policy: MissPolicy
    binding_source: BindingSource
    variants: tuple[str, ...]
    debt_cap_periods: int
    # The walked charge the outcome write restates. Read beside the row rather than derived from
    # the log, so a reader without the log's whole history still answers with this figure.
    charged_misses: int
    created_at: datetime

    def cadence(self) -> Cadence:
        """The cadence this row's three columns name."""
        return build_cadence(
            self.cadence_kind,
            times_per_week=self.cadence_times_per_week,
            approx_days=self.cadence_approx_days,
        )

    def duration(self) -> Duration:
        """The occurrence span this row's two columns name. Fixed when they are equal."""
        return Duration(
            min_minutes=self.duration_min_minutes, max_minutes=self.duration_max_minutes
        )

    def as_habit(self) -> Habit:
        """The entity the invariants and the two derivations are stated over.

        Building one applies X3 and X4, so a row that somehow held a rotation without variants
        would be refused here rather than reaching a cursor derivation with nothing to index.
        """
        return Habit(
            id=self.id,
            cadence=self.cadence(),
            duration=self.duration(),
            miss_policy=self.miss_policy,
            binding_source=self.binding_source,
            variants=self.variants,
            debt_cap_periods=self.debt_cap_periods,
        )


def columns_of(cadence: Cadence) -> tuple[CadenceKind, int | None, int | None]:
    """A cadence as the discriminator and the two nullable numbers a row stores.

    The inverse of :meth:`HabitRecord.cadence`, kept beside it so the two halves of one mapping
    are read together. Stated here rather than in the repository because both the create path
    and the update path need it, and a second copy is how the two would come to disagree.
    """
    return (
        cadence_kind(cadence),
        cadence.count if isinstance(cadence, TimesPerWeek) else None,
        cadence.days if isinstance(cadence, EveryApproxDays) else None,
    )
