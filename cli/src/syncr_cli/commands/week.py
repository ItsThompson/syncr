"""``week show``: the week, as a plan.

One read command, and the one that proves the whole spine: it authenticates with a bearer token,
reads the composed week view, names its Areas, renders the ledger for a person and the api's own
payload for an agent, and exits 8 when the week cannot hold its commitments.

**Two reads, not one.** A block carries the Area it is charged to as an identifier, and a ledger
of identifiers is not a ledger. The Areas are a bounded collection -- as many as a person holds
life categories -- so naming them costs one small request rather than a lookup per block.

**An Area read that fails does not fail the ledger.** The week is what was asked for; a name is
how a row reads. So a refused or unreadable Area list leaves the rows naming no Area rather than
losing the whole week, and the notice says so.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from syncr_cli.errors import CliError
from syncr_cli.parser import add_verb, register_command
from syncr_cli.rendering.ledger import WeekLedger
from syncr_cli.results import CliResult
from syncr_cli.wire.reading import mapping, mappings, text
from syncr_cli.wire.week import WeekView

if TYPE_CHECKING:
    from syncr_cli.api_client import ApiClient
    from syncr_cli.notices import Notices
    from syncr_cli.parser import Invocation, Parser, Verbs
    from syncr_cli.runtime import Runtime

NOUN = "week"

AREAS_DOCUMENT = "areas"


def register(nouns: Verbs, shared: Parser) -> None:
    """Put the week commands in the catalog."""
    verbs = add_verb(nouns, shared, noun=NOUN, noun_help="Read a week")
    register_command(
        verbs,
        noun=NOUN,
        verb="show",
        summary=(
            "The week as a plan: the readings, the verdict and its provenance, and the day rows. "
            "Exits 8 when the week cannot hold its commitments"
        ),
        handler=show,
        shared=shared,
        examples=(
            "syncr week show",
            "syncr week show --week 2026-W07",
            "syncr week show --json | jq '.data.readings'",
        ),
    )


def show(runtime: Runtime, _invocation: Invocation) -> CliResult:
    """Read one week and answer with everything three renderings need."""
    week = WeekView.read(runtime.client.read_week(str(runtime.settings.week)))
    return CliResult.succeeded(
        WeekLedger(week=week, area_names=area_names(runtime.client, runtime.notices)),
        verdict=week.verdict,
        operation=week.operation,
    )


def area_names(client: ApiClient, notices: Notices) -> dict[UUID, str]:
    """Every Area of this tenant, by identifier, or nothing and a notice saying why."""
    try:
        payload = mapping(client.list_areas(), AREAS_DOCUMENT)
        return {
            UUID(text(area, "id", AREAS_DOCUMENT)): text(area, "name", AREAS_DOCUMENT)
            for area in mappings(payload, "areas", AREAS_DOCUMENT)
        }
    except (CliError, ValueError) as error:
        notices.state(
            f"the Areas could not be read ({error}), so the ledger's Area column reads '--'. "
            "The week itself is unaffected."
        )
        return {}
