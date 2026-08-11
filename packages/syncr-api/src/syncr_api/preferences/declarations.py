"""What a request asked to declare, as the service takes it.

These sit between the route that read the request and the service that applies it, so the service
never imports a wire schema and the route never decides anything.

**There is one declaration and no change shape.** A preference is replaced wholly rather than
patched, so there is no absent-versus-null distinction to carry and no merge to express: every
field of the declaration is stated by every request, and a value the caller leaves out is null
rather than unchanged. That is what the routes being ``PUT`` rather than ``PATCH`` means.

**A declaration carries no owner.** The owner is in the path, and the service resolves it against
the row it addresses before building anything, so a declaration cannot name an owner that does not
exist and a route cannot decide which owner it applies to.

**A declaration built from an override's request shape carries no cap**, because that shape has no
field for one. The service names ``None`` at that call, and the entity refuses a cap on any owner
but an Area, so the two are one rule stated where each can see it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.preferences import LocalTimeWindow, Preference, authored_windows

if TYPE_CHECKING:
    from datetime import time

    from syncr_domain.preferences import PreferenceOwner, PreferenceStrength


@dataclass(frozen=True, slots=True)
class DeclaredWindow:
    """A window as a request states it: two wall times that are not yet domain windows.

    Kept as the request's own shape rather than converted at the route, because every refusal a
    window carries is the domain's, and the domain is only entered where a rejection is mapped to a
    422. A route that built the domain value itself would raise where nothing maps it, which is a
    500 for a body the caller could fix.
    """

    start: time
    end: time

    def as_windows(self) -> tuple[LocalTimeWindow, ...]:
        """The domain windows this pair names, or a domain rejection saying why it names none.

        Two of them where the stretch wraps past midnight, and this is the authoring boundary that
        split is stated to happen at: one stretch arrives and the halves are what gets stored.
        """
        return authored_windows(start=self.start, end=self.end)


@dataclass(frozen=True, slots=True)
class PreferenceDeclaration:
    """A preference to put on one owner, whole.

    ``windows`` may be empty, and on an override that is the statement rather than an omission: it
    replaces its Area's windows with none.
    """

    windows: tuple[DeclaredWindow, ...]
    strength: PreferenceStrength
    preferred_duration_minutes: int | None
    max_per_day_minutes: int | None

    def as_preference(self, owner: PreferenceOwner) -> Preference:
        """The entity every invariant is stated over, for the owner the path named.

        Called from inside the one place a domain rejection becomes a 422, and that includes the
        window bounds: they are converted here rather than at the route for the same reason.
        """
        return Preference(
            owner=owner,
            windows=tuple(window for declared in self.windows for window in declared.as_windows()),
            strength=self.strength,
            preferred_duration_minutes=self.preferred_duration_minutes,
            max_per_day_minutes=self.max_per_day_minutes,
        )
