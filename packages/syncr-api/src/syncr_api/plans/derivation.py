"""The columns re-derived from a plan document, computed in exactly one place.

The document is authoritative and the scalar columns beside it exist so a week can be
queried without opening it. That only holds while the two agree, and they only agree if
nothing sets a scalar independently. So every writer of a document-describing column goes
through this module, and no repository method takes one as an argument.

Today that is one column, ``iso_week``. A queryable scalar added later is derived here as
well rather than accepted from the caller, and both writers get it at once.

The rest of the document's interior is not read, not validated, and not typed here. JSONB
is schemaless at the database level and a Pydantic model enforces the document's shape on
the way in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.plans.errors import PlanDocumentRejected
from syncr_domain.weeks import IsoWeek, IsoWeekError

if TYPE_CHECKING:
    from syncr_api.core.columns import JsonDocument

DOCUMENT_ISO_WEEK_KEY = "iso_week"


def derive_iso_week(document: JsonDocument) -> IsoWeek:
    """The week the document is for, read from the document itself.

    Parsed rather than copied, so a row can only be written for a week that exists: a
    document naming ``2026-W53`` in a year with 52 weeks is rejected here rather than
    stored and discovered by whatever reads it next.
    """
    value = document.get(DOCUMENT_ISO_WEEK_KEY)
    if not isinstance(value, str):
        raise PlanDocumentRejected(
            f"the document carries no {DOCUMENT_ISO_WEEK_KEY!r} string, so the week it "
            "describes cannot be derived"
        )
    try:
        return IsoWeek.parse(value)
    except IsoWeekError as error:
        raise PlanDocumentRejected(str(error)) from error
