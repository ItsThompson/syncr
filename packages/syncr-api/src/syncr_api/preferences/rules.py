"""How a preference is refused, and the one thing these routes 404 on.

**They 404 on the OWNER and never on the preference.** An Area, a Habit, or a Task the tenant does
not hold is a missing resource, because the identifier is in the path. A missing preference is not:
an owner that declares none still has one in effect through its Area, or has none in effect at all,
and both are answers rather than absences. That is one rule covering nine routes, which is why it
is stated here rather than per route.

The domain's refusal is translated rather than restated. A preference rejection names the field it
refused in the entity's own spelling, and the wire spells that field in camelCase, so deriving the
wire name from the domain name means a renamed field cannot leave the two disagreeing and the
caller gets a 422 pointing at the control to fix.

Nothing here compares a strength against a vocabulary, and nothing compares a cap against its
owner. The first is the request schema's enum and the second is the entity's invariant, and a
second statement of either would be a weaker one that could pass while the first refused.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Final

from pydantic.alias_generators import to_camel

from syncr_api.areas.config import AREA_RESOURCE
from syncr_api.core.errors import FieldError, NotFound, ValidationFailed
from syncr_api.habits.config import HABIT_RESOURCE
from syncr_api.preferences.config import PREFERENCE_RESOURCE
from syncr_api.tasks.config import TASK_RESOURCE
from syncr_domain.preferences import PreferenceChainOutOfOrder, PreferenceError, PreferenceOwnerKind

if TYPE_CHECKING:
    from collections.abc import Iterator

# What a refusal calls each kind of owner, taken from the module that owns the word so a 404 here
# reads the same as that module's own.
OWNER_RESOURCE: Final[dict[PreferenceOwnerKind, str]] = {
    PreferenceOwnerKind.AREA: AREA_RESOURCE,
    PreferenceOwnerKind.HABIT: HABIT_RESOURCE,
    PreferenceOwnerKind.TASK: TASK_RESOURCE,
}


def unknown_owner(kind: PreferenceOwnerKind) -> NotFound:
    """The 404 a request addressing an owner that does not exist carries.

    Answered the same way whether the identifier is unknown or belongs to another tenant, so the
    response discloses nothing about which.
    """
    named = OWNER_RESOURCE[kind]
    return NotFound(
        f"No {named} matches that identifier, so it has no {PREFERENCE_RESOURCE}. Nothing was "
        f"changed. Declare the {named} first: a {PREFERENCE_RESOURCE} says when ITS work should "
        "happen."
    )


@contextmanager
def stated_rejection() -> Iterator[None]:
    """Turn a domain refusal into the status and the field the boundary owes it.

    Both are 422. A preference rejection is a bad value in the request, and a chain refusal is a
    bad call this module made: the second cannot be reached from any request, so it is mapped for
    the reason ``habits.rules`` maps its cursor refusal, which is that a stored row the resolution
    cannot read should not read as the server breaking.
    """
    try:
        yield
    except PreferenceError as error:
        raise ValidationFailed(
            f"That {PREFERENCE_RESOURCE} was not accepted: {error}. Nothing was changed. Every "
            f"{PREFERENCE_RESOURCE} that already exists still reads as it did.",
            errors=[FieldError(field=to_camel(error.field.value), message=str(error))],
        ) from error
    except PreferenceChainOutOfOrder as error:
        raise ValidationFailed(
            f"That {PREFERENCE_RESOURCE} could not be resolved: {error}. Nothing was changed."
        ) from error
