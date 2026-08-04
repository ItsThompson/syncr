"""What a request asked to declare or change, as the service takes it.

These sit between the route that read the request and the service that applies it, so the
service never imports a wire schema and the route never decides anything.

**The default that makes a routine inelastic is stated here, once.** A declaration whose
minimum is unstated takes the target duration, so ``Lunch 45m`` cannot be compressed by
anything until the user gives it a floor below its target. There is no sleep-specific rule
anywhere: sleep is simply the routine users give an elastic range to.

Every field of a change is two-valued rather than three. No column on a routine is nullable, so
there is nothing for an explicit null to clear: a field is either stated or left alone, and the
schema refuses a null on all five.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from syncr_api.core.patches import resolved
from syncr_domain.routines import RoutineSpan

if TYPE_CHECKING:
    from datetime import time

    from syncr_api.core.patches import Patched
    from syncr_api.routines.records import RoutineRecord


@dataclass(frozen=True, slots=True)
class RoutineDeclaration:
    """One routine to declare.

    ``min_duration_minutes`` is ``None`` when the caller stated no floor, which is not the same
    as stating zero: zero is refused, and an unstated floor becomes the target duration.
    """

    title: str
    target_time: time
    duration_minutes: int
    min_duration_minutes: int | None
    flex_band_minutes: int

    def span(self) -> RoutineSpan:
        """The domain span this declaration names, with an unstated floor equal to the target.

        Building it is what validates it: a duration of nothing, a floor above the target, and a
        band wider than the domain allows are all refused here rather than stored.
        """
        return RoutineSpan(
            target_time=self.target_time,
            duration_minutes=self.duration_minutes,
            min_duration_minutes=self.min_duration_minutes
            if self.min_duration_minutes is not None
            else self.duration_minutes,
            flex_band_minutes=self.flex_band_minutes,
        )


@dataclass(frozen=True, slots=True)
class RoutineChange:
    """What one ``PATCH`` asked to change on a routine.

    ``min_duration_minutes`` is where the sleep floor is set. It is a field of the routine like
    any other, which is the point: one home for the value, and the solver reads it from the
    domain rather than from a settings row.
    """

    title: Patched[str]
    target_time: Patched[time]
    duration_minutes: Patched[int]
    min_duration_minutes: Patched[int]
    flex_band_minutes: Patched[int]

    def applied_to(self, current: RoutineRecord) -> RoutineRecord:
        """``current`` with every field this change stated replaced.

        Merged before it is validated, because a floor and a target are only legal with respect
        to each other: lowering a target below a stored floor is as much a violation as raising
        a floor above a stored target, and neither request can be judged on its own.
        """
        return replace(
            current,
            title=resolved(self.title, current.title),
            target_time=resolved(self.target_time, current.target_time),
            duration_minutes=resolved(self.duration_minutes, current.duration_minutes),
            min_duration_minutes=resolved(self.min_duration_minutes, current.min_duration_minutes),
            flex_band_minutes=resolved(self.flex_band_minutes, current.flex_band_minutes),
        )
