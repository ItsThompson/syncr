"""The immutable view of a preference row, and where it meets the domain shapes.

A repository hands one of these back rather than a mapped instance, so a service cannot trigger
a load it did not ask for, a fake repository in a service test is a function returning a frozen
dataclass, and nothing downstream can change a row by assigning to it.

This is not the wire shape: ``schemas.py`` owns that, so a column added to the table does not
appear in a response by sharing a name with a field.

:meth:`PreferenceRecord.as_preference` is where the row meets the entity every invariant is
stated over, and it is a method rather than a stored field for the same reason
``HabitRecord.as_habit`` is: the entity is a reading of the row, and storing a second copy of one
would be storing a value that can disagree with the row it came from.

**The owner is resolved before a record exists**, which departs from ``HabitRecord`` holding its
cadence as three columns. The reason is that the owner's KIND is read by an invariant: a daily
cap is an Area's alone. A record that could hold a kind with no identifier for it would let a
fake repository in a service test produce a preference the table cannot store, which is the one
shape of test that passes while the product is wrong.

The window list crosses the JSONB boundary here, in both directions, so the two halves of one
mapping are read together. A stored list that is not a list of two wall times is refused as a
``PreferenceError`` rather than raised as a ``KeyError``: the boundary owes such a row a stated
422 naming the field, not a 500 saying the server broke when what broke is one row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import TYPE_CHECKING, Final

from syncr_domain.preferences import (
    LocalTimeWindow,
    Preference,
    PreferenceError,
    PreferenceField,
    PreferenceOwner,
    PreferenceOwnerKind,
    PreferenceStrength,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

    from syncr_domain.identifiers import AreaId, HabitId, PreferenceId, TaskId, TenantId

# The two keys a stored window object holds. Named rather than positional, so a row read in
# `psql` says which bound is which.
WINDOW_START_KEY: Final = "start"
WINDOW_END_KEY: Final = "end"


class UnattributedPreferenceRow(ValueError):
    """A stored row names a kind of owner and holds no identifier for it.

    Not a ``PreferenceError``: nothing a caller sent is wrong, so there is no field to name and
    no 422 to raise. The table's own constraint pairs the discriminator with the reference the
    kind names, so reaching this means that constraint is gone, which is a server fault and is
    reported as one.
    """


def owner_columns(owner: PreferenceOwner) -> tuple[AreaId | None, HabitId | None, TaskId | None]:
    """An owner as the three nullable references a row stores. Exactly one is set.

    The inverse of :func:`owner_of`, kept beside it so the two halves of one mapping are read
    together, and stated here rather than in the repository because the create path and the
    replace path both need it.
    """
    return (
        owner.id if owner.kind is PreferenceOwnerKind.AREA else None,
        owner.id if owner.kind is PreferenceOwnerKind.HABIT else None,
        owner.id if owner.kind is PreferenceOwnerKind.TASK else None,
    )


def owner_of(
    kind: PreferenceOwnerKind,
    *,
    area_id: AreaId | None,
    habit_id: HabitId | None,
    task_id: TaskId | None,
) -> PreferenceOwner:
    """The one thing a row's discriminator and its three references name."""
    named = {
        PreferenceOwnerKind.AREA: area_id,
        PreferenceOwnerKind.HABIT: habit_id,
        PreferenceOwnerKind.TASK: task_id,
    }[kind]
    if named is None:
        raise UnattributedPreferenceRow(
            f"a stored preference names a {kind.value} owner and holds no {kind.value} "
            "identifier, so it belongs to nothing"
        )
    return PreferenceOwner(kind=kind, id=named)


def windows_as_json(windows: Sequence[LocalTimeWindow]) -> list[dict[str, str]]:
    """The window list as the JSONB column stores it, in the order the entity canonicalized."""
    return [
        {WINDOW_START_KEY: window.start.isoformat(), WINDOW_END_KEY: window.end.isoformat()}
        for window in windows
    ]


def windows_from_json(stored: object) -> tuple[LocalTimeWindow, ...]:
    """The window list a stored JSONB value names, or a stated refusal of the row.

    Every rejection the wall times themselves produce is already a ``PreferenceError`` from
    :class:`~syncr_domain.preferences.LocalTimeWindow`, an offset included, so this adds only the
    refusals a schemaless column allows and the entity cannot see: a value that is not a list, an
    element that is not an object holding the two keys, and a bound that is not a time.
    """
    if not isinstance(stored, list):
        raise PreferenceError(
            PreferenceField.WINDOWS,
            f"stored windows are an ordered list and this row holds {type(stored).__name__}",
        )
    return tuple(_window_from_json(element) for element in stored)


def _window_from_json(element: object) -> LocalTimeWindow:
    if not isinstance(element, dict):
        raise PreferenceError(
            PreferenceField.WINDOWS,
            f"a stored window is an object naming {WINDOW_START_KEY} and {WINDOW_END_KEY}, and "
            f"this one is {type(element).__name__}",
        )
    return LocalTimeWindow(
        start=_wall_time(element, WINDOW_START_KEY), end=_wall_time(element, WINDOW_END_KEY)
    )


def _wall_time(element: Mapping[str, object], key: str) -> time:
    stored = element.get(key)
    if not isinstance(stored, str):
        raise PreferenceError(
            PreferenceField.WINDOWS,
            f"a stored window names its {key} as a wall time, and this one holds "
            f"{type(stored).__name__}",
        )
    try:
        return time.fromisoformat(stored)
    except ValueError as error:
        raise PreferenceError(
            PreferenceField.WINDOWS, f"a stored window's {key} is not a time: {stored!r}"
        ) from error


@dataclass(frozen=True, slots=True)
class PreferenceRecord:
    """One preference, as persistence knows it."""

    id: PreferenceId
    tenant_id: TenantId
    owner: PreferenceOwner
    windows: tuple[Mapping[str, str], ...]
    strength: PreferenceStrength
    preferred_duration_minutes: int | None
    max_per_day_minutes: int | None
    created_at: datetime

    def as_preference(self) -> Preference:
        """The entity every invariant is stated over.

        Building one applies the cap's owner rule, both window bounds, and the ideal duration's
        grid, so a row that somehow held a cap on a habit is refused here rather than reaching a
        resolution that would hand the solver an override relaxing a hard constraint.
        """
        return Preference(
            owner=self.owner,
            windows=windows_from_json([dict(window) for window in self.windows]),
            strength=self.strength,
            preferred_duration_minutes=self.preferred_duration_minutes,
            max_per_day_minutes=self.max_per_day_minutes,
        )
