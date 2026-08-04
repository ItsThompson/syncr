"""What a habit has to satisfy before it is stored, and how a domain rejection becomes a status.

Two kinds of rule meet here and they are kept apart on purpose.

The **comparison between two stored rows** lives at the service layer because a request schema
cannot see the second row: whether the Area a habit claims exists at all. A rule stated in a
schema would be a second, weaker statement of this one.

The **invariants** live in ``syncr_domain.habits`` and are only MAPPED here. X3 and X4 are a
relation between a habit's own two fields, so they are stated once, in the pure package, and
this module turns that rejection into the 422 the boundary owes it. That is why there is no
comparison of a binding source against a variant list anywhere in this module or in
``schemas.py``.

Every rejection the entity produces is one ``HabitError``, so one clause covers them all and the
message the entity wrote is what the caller reads. The alternative was a subclass per bound,
which would be nine exception types the boundary maps to one status.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from syncr_api.areas.rules import unknown_area
from syncr_api.core.errors import ValidationFailed
from syncr_api.habits.config import HABIT_RESOURCE
from syncr_domain.cursor import NoRotationCursor
from syncr_domain.habits import HabitError

if TYPE_CHECKING:
    from collections.abc import Iterator

# The wire spelling, which is what a caller reads in `errors[].field`. camelCase because that is
# what the document advertises and what a generated client sends.
AREA_FIELD = "areaId"


def unknown_area_for_a_habit() -> ValidationFailed:
    """The 422 a request naming an Area that does not exist carries.

    Answered the same way whether the identifier is unknown or belongs to another tenant, so the
    response discloses nothing about which.
    """
    return ValidationFailed(
        f"No Area matches that identifier, so a {HABIT_RESOURCE} cannot be declared inside it. "
        "Nothing was changed. Declare the Area first: a habit's occurrences count toward exactly "
        "one Area, which is what keeps an hour attributable once.",
        errors=unknown_area(AREA_FIELD),
    )


@contextmanager
def stated_rejection() -> Iterator[None]:
    """Turn a domain rejection into the status and the wording the boundary owes it.

    ``NoRotationCursor`` is caught as well as ``HabitError``, and not because a route can ask for
    a cursor on a fixed habit: nothing here does, and the reading a response renders answers
    ``None`` for such a habit rather than raising. It is caught because a stored row whose
    binding source and variant list disagree would surface as one, and a 500 would say the
    server broke when what broke is one row.
    """
    try:
        yield
    except HabitError as error:
        raise ValidationFailed(
            f"That {HABIT_RESOURCE} was not accepted: {error}. Nothing was changed. Every habit "
            "that already exists still reads as it did."
        ) from error
    except NoRotationCursor as error:
        raise ValidationFailed(
            f"That {HABIT_RESOURCE} was not accepted: {error}. Nothing was changed."
        ) from error
