"""Naming an Area, and what a surface prints when it cannot.

Every ledger in this CLI charges its rows to an Area, and every payload carries that Area as an
identifier: a column of identifiers is not a ledger. So both the week's ledger and the backlog take
one small extra read, because the Areas are a bounded collection -- as many as a person holds life
categories -- and naming them costs one request rather than a lookup per row.

**Keyed by the identifier as the wire spells it.** A block's ``areaId`` and a task's are the same
string, so one map serves both and no surface converts between two keyings of one idea.

**An Area read that fails does not fail the command.** The week, or the backlog, is what was asked
for; a name is how a row reads. So a refused or unreadable Area list leaves the rows naming no Area
rather than losing the answer, and a notice on stderr says which of the two a ``--`` means.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_cli.errors import CliError
from syncr_cli.wire.reading import mapping, mappings, text

if TYPE_CHECKING:
    from syncr_cli.api_client import ApiClient
    from syncr_cli.notices import Notices

AREAS_DOCUMENT = "areas"

# What a row's Area column holds when this read did not name one: the frame, an imported anchor, a
# forbidden window, and an Area a failed read could not name.
NO_AREA = "--"


def area_names(client: ApiClient, notices: Notices) -> dict[str, str]:
    """Every Area of this tenant, by identifier, or nothing and a notice saying why."""
    try:
        payload = mapping(client.list_areas(), AREAS_DOCUMENT)
        return {
            text(area, "id", AREAS_DOCUMENT): text(area, "name", AREAS_DOCUMENT)
            for area in mappings(payload, "areas", AREAS_DOCUMENT)
        }
    except CliError as error:
        notices.state(
            f"the Areas could not be read ({error}), so the Area column reads '{NO_AREA}'. "
            "The answer itself is unaffected."
        )
        return {}
