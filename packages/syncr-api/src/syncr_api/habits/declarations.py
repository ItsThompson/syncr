"""What a request asked to declare or change, as the service takes it.

These sit between the route that read the request and the service that applies it, so the
service never imports a wire schema and the route never decides anything.

**A declaration carries the request's own shape, not the domain's.** A cadence arrives as a kind
and two nullable numbers, and a duration as a floor and an optional ceiling, which is how a
request states them. Turning either into a domain value is what
:meth:`HabitDeclaration.as_habit` does, and the service calls it inside the one place a domain
rejection becomes a 422. Building them in the route instead would put the rejection where
nothing maps it.

Every field of a change is two-valued rather than three: absent leaves the stored value alone,
and a value replaces it. Nothing on a habit is nullable, so there is no third case to express
and the schema refuses an explicit null rather than reading one as "no change".

The two duration bounds are patched independently, because a request may state either alone:
raising a ceiling states the maximum and keeps the stored floor.

A change carries no Area, because a habit's Area is declared once: the hours already spent on its
occurrences were attributed to that Area, so moving it would rewrite reported history.

It carries no cursor either, and there is nowhere for one to be carried: the cursor is derived,
so a change naming it would be a change to something that is not stored.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from syncr_api.core.patches import resolved
from syncr_domain.habits import Duration, Habit, build_cadence

if TYPE_CHECKING:
    from syncr_api.core.patches import Patched
    from syncr_api.habits.records import HabitRecord
    from syncr_domain.habits import BindingSource, Cadence, CadenceKind, MissPolicy
    from syncr_domain.identifiers import AreaId, HabitId


@dataclass(frozen=True, slots=True)
class DeclaredCadence:
    """A cadence as a request states it: a kind, and the one number that kind uses.

    The pair a kind does not use is refused by :func:`syncr_domain.habits.build_cadence`, so a
    body naming ``daily`` with a count is a stated 422 rather than a count silently dropped.
    """

    kind: CadenceKind
    times_per_week: int | None
    approx_days: int | None

    def as_cadence(self) -> Cadence:
        """The cadence this triple names, or a domain rejection saying why it names none."""
        return build_cadence(
            self.kind, times_per_week=self.times_per_week, approx_days=self.approx_days
        )


@dataclass(frozen=True, slots=True)
class HabitDeclaration:
    """One habit to declare, inside an Area that already exists."""

    area_id: AreaId
    title: str
    cadence: DeclaredCadence
    min_duration_minutes: int
    max_duration_minutes: int | None
    miss_policy: MissPolicy
    binding_source: BindingSource
    variants: tuple[str, ...]
    debt_cap_periods: int

    def as_habit(self, habit_id: HabitId) -> Habit:
        """The entity this declaration names, which is where every invariant applies.

        An absent ceiling means the duration is fixed, so it resolves to the floor: this span or
        nothing. The identifier is an argument because a declaration does not have one yet and
        the entity does, so the habit that is validated and the row that is written carry one
        identity rather than two.
        """
        return Habit(
            id=habit_id,
            cadence=self.cadence.as_cadence(),
            duration=Duration(
                min_minutes=self.min_duration_minutes,
                max_minutes=self.max_duration_minutes
                if self.max_duration_minutes is not None
                else self.min_duration_minutes,
            ),
            miss_policy=self.miss_policy,
            binding_source=self.binding_source,
            variants=self.variants,
            debt_cap_periods=self.debt_cap_periods,
        )


@dataclass(frozen=True, slots=True)
class HabitChange:
    """What one ``PATCH`` asked to change on a habit.

    ``binding_source`` and ``variants`` travel separately even though X3 and X4 pair them,
    because a request may state either alone: switching a rotation to fixed states the source and
    an empty list, and re-ordering a split states the list and leaves the source. The MERGED pair
    is what the entity validates, which is why neither is checked here.
    """

    title: Patched[str]
    cadence: Patched[DeclaredCadence]
    min_duration_minutes: Patched[int]
    max_duration_minutes: Patched[int]
    miss_policy: Patched[MissPolicy]
    binding_source: Patched[BindingSource]
    variants: Patched[tuple[str, ...]]
    debt_cap_periods: Patched[int]

    def applied_to(self, current: HabitRecord) -> HabitRecord:
        """``current`` with every field this change stated replaced.

        The result is a record rather than an entity, so the caller holds one object it both
        validates and writes. Nothing is checked here: a merged record can be nonsense, and
        :meth:`syncr_api.habits.records.HabitRecord.as_habit` is what says so.
        """
        stated = resolved(
            self.cadence,
            DeclaredCadence(
                kind=current.cadence_kind,
                times_per_week=current.cadence_times_per_week,
                approx_days=current.cadence_approx_days,
            ),
        )
        return replace(
            current,
            title=resolved(self.title, current.title),
            cadence_kind=stated.kind,
            cadence_times_per_week=stated.times_per_week,
            cadence_approx_days=stated.approx_days,
            duration_min_minutes=resolved(self.min_duration_minutes, current.duration_min_minutes),
            duration_max_minutes=resolved(self.max_duration_minutes, current.duration_max_minutes),
            miss_policy=resolved(self.miss_policy, current.miss_policy),
            binding_source=resolved(self.binding_source, current.binding_source),
            variants=resolved(self.variants, current.variants),
            debt_cap_periods=resolved(self.debt_cap_periods, current.debt_cap_periods),
        )
