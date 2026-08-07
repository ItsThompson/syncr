"""``day confirm``: convert presumption into record for one date.

**The date defaults to today**, because the day a person answers for is almost always the one they
have just lived. Today is the machine's own local date, which is what "today" means to the person at
the terminal; a caller in a zone ahead of the server's states the date rather than having one
inferred.

**Confirming answers for every block of the day.** A block nobody said anything about is recorded as
presumed complete, which is what the presumption means, and the day then counts toward reviews and
toward learning. The settled ledger is read back, so a caller sees what it just recorded rather than
what it asked for.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Final

from syncr_cli.arguments import stated_date
from syncr_cli.parser import add_verb, register_command
from syncr_cli.rendering.day_views import DayLedgerView
from syncr_cli.results import CliResult
from syncr_cli.wire.day import DayLedger

if TYPE_CHECKING:
    from syncr_cli.parser import Invocation, Parser, Verbs
    from syncr_cli.runtime import Runtime

NOUN = "day"

# The lead word the settled ledger carries, so a reader sees what this command did rather than only
# what the day now holds.
CONFIRMED: Final = "confirmed"


def register(nouns: Verbs, shared: Parser) -> None:
    """Put the day command in the catalog."""
    verbs = add_verb(nouns, shared, noun=NOUN, noun_help="Answer for a day")
    confirming = register_command(
        verbs,
        noun=NOUN,
        verb="confirm",
        summary=(
            "Convert presumed to recorded for one date, defaulting to today, and read the settled "
            "ledger back"
        ),
        handler=confirm,
        shared=shared,
        examples=(
            "syncr day confirm",
            "syncr day confirm 2026-02-10",
            "syncr day confirm --json | jq '.data.unconfirmedDays'",
        ),
    )
    confirming.add_argument(
        "on",
        nargs="?",
        metavar="DATE",
        type=stated_date,
        help="the date to answer for, as 2026-02-10. Defaults to this machine's today",
    )


def confirm(runtime: Runtime, invocation: Invocation) -> CliResult:
    """Settle one date and answer with the ledger as it now reads."""
    on = invocation.value("on", date) or runtime.host.today
    settled = DayLedger.read(
        runtime.client.confirm_day(on, key=invocation.idempotency_key({"date": on.isoformat()}))
    )
    return CliResult.succeeded(DayLedgerView(day=settled, lead=CONFIRMED))
