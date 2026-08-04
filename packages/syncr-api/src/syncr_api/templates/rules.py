"""What a day-shape declaration has to satisfy before it is stored, and how it is refused.

Three of these rules are stated over rows the tenant already holds, which is why they live here
rather than in a request schema: a schema sees one request, and none of these is about one
request.

The fourth is a translation. The domain refuses a span by naming the field it refused, in the
span's own spelling, and the wire spells that field in camelCase. Deriving the wire name from
the domain name means a renamed field cannot leave the two disagreeing, and the caller gets a
422 that points at the control to fix rather than at the request as a whole.

Nothing here checks that a concrete entry names a routine or a habit that exists. Those tables
are created by later revisions, so at this point a binding is an identifier this package cannot
resolve. The entry's ``binding_target`` records which table will answer for it.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from pydantic.alias_generators import to_camel

from syncr_api.areas.config import AREA_RESOURCE
from syncr_api.areas.rules import unknown_area
from syncr_api.core.errors import Conflict, FieldError, ValidationFailed
from syncr_api.templates.config import DAY_TYPE_RESOURCE
from syncr_domain.templates import TemplateEntryError, WeekPatternIncomplete

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from syncr_api.areas.records import AreaRecord
    from syncr_api.templates.records import DayTypeRecord, TemplateEntryRecord, TemplateRecord
    from syncr_domain.identifiers import DayTypeId, TemplateEntryId


def find_entry(
    entry_id: TemplateEntryId, entries: Sequence[TemplateEntryRecord]
) -> TemplateEntryRecord | None:
    """The entry with this identifier among a shape's own, or ``None``.

    Looked up inside the shape the request named rather than by identifier alone, so an entry of
    another shape is absent here rather than editable through the wrong path.
    """
    return next((entry for entry in entries if entry.id == entry_id), None)


def require_a_declared_day_type(day_type_id: DayTypeId, existing: Sequence[DayTypeRecord]) -> None:
    """Refuse a day type this tenant has not declared.

    Answered the same way whether the identifier is unknown or belongs to another tenant, so the
    response discloses nothing about which.
    """
    if not any(day_type.id == day_type_id for day_type in existing):
        raise ValidationFailed(
            f"No {DAY_TYPE_RESOURCE} matches that identifier. Nothing was changed. Declare the "
            f"{DAY_TYPE_RESOURCE} first: a shape is the shape OF one, and the week pattern maps "
            "weekdays onto it.",
            errors=unknown_day_type("dayTypeId"),
        )


def require_an_unused_day_type_name(name: str, existing: Sequence[DayTypeRecord]) -> None:
    """Refuse a name another day type already holds.

    The week pattern's seven rows and the template list both identify a day type by its name, so
    two holding one name would leave the user choosing between two identical rows.
    """
    if any(day_type.name == name for day_type in existing):
        raise Conflict(
            f"Another {DAY_TYPE_RESOURCE} already carries that name. Nothing was changed. The "
            "week pattern names a day type by its name, so two cannot share one. Every day type "
            "that already exists still reads as it did."
        )


def require_an_unshaped_day_type(shaped: TemplateRecord | None) -> None:
    """Refuse a second shape for a day type that already has one.

    Materializing a date resolves its weekday to a day type and the day type to a shape, so two
    shapes for one day type would need a rule deciding which parts of which one applied. That
    rule is what this model does not have, and does not need: recurrence is a habit's cadence.
    """
    if shaped is not None:
        raise Conflict(
            f"That {DAY_TYPE_RESOURCE} already has the shape {shaped.name!r}, so a second was "
            "not created. Nothing was changed. A day type has one shape, because materializing "
            "a date resolves its weekday to a day type and the day type to one shape. Edit the "
            "existing shape's entries, or declare another day type."
        )


def unknown_day_type(field: str) -> list[FieldError]:
    """The field-level error a request naming a day type that does not exist carries."""
    return [FieldError(field=field, message=f"No {DAY_TYPE_RESOURCE} matches that identifier.")]


def require_a_declared_area(area: AreaRecord | None) -> None:
    """Refuse an entry naming an Area this tenant has not declared.

    Takes the row the repository found rather than an identifier, because the question is
    whether the Area exists for THIS tenant and only a scoped read answers that.
    """
    if area is None:
        raise ValidationFailed(
            f"No {AREA_RESOURCE} matches that identifier, so an entry cannot name it. Nothing "
            "was changed. Declare the Area first: a slot is a duration OF one, which is what "
            "lets the solver choose the content.",
            errors=unknown_area("areaId"),
        )


@contextmanager
def stated_rejection() -> Iterator[None]:
    """Turn a domain refusal into the status and the field the boundary owes it.

    Both are bad values in the request rather than state conflicts, so both are 422. The span
    rejection names its field, and the wire name is derived from the domain name rather than
    mapped through a table a fourth field would have to be added to.
    """
    try:
        yield
    except TemplateEntryError as error:
        raise ValidationFailed(
            f"The entry was not accepted: {error}. Nothing was changed.",
            errors=[FieldError(field=to_camel(error.field.value), message=str(error))],
        ) from error
    except WeekPatternIncomplete as error:
        raise ValidationFailed(
            f"The week pattern was not accepted: {error}. Nothing was changed. A pattern is "
            "replaced whole rather than patched, so every weekday has to be named in the "
            "request."
        ) from error
