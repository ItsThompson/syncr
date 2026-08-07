"""``week show``: the week, as a plan.

The read that proves the whole spine: it authenticates with a bearer token, reads the composed week
view, names its Areas, renders the ledger for a person and the api's own payload for an agent, and
exits 8 when the week cannot hold its commitments.

**Two reads, not one.** A block carries the Area it is charged to as an identifier, and a ledger
of identifiers is not a ledger. How the second read degrades when it fails is
:mod:`syncr_cli.areas`, which the backlog's rendering shares: one policy, so a ``--`` means the
same thing on both surfaces.

**One composition of the week's ledger, reached by three commands.** ``plan show`` prints the same
ledger and ``plan solve --wait`` prints its heading group, so both read the week through
:func:`read_week` rather than composing a second one: two compositions of one view is how two
surfaces come to disagree about a figure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_cli.areas import area_names
from syncr_cli.parser import add_verb, register_command
from syncr_cli.rendering.ledger import WeekLedger
from syncr_cli.results import CliResult
from syncr_cli.wire.week import WeekView

if TYPE_CHECKING:
    from syncr_cli.parser import Invocation, Parser, Verbs
    from syncr_cli.runtime import Runtime

NOUN = "week"


@dataclass(frozen=True, slots=True)
class ReadWeek:
    """One week's read: the view it came from, and the ledger that prints it."""

    view: WeekView
    ledger: WeekLedger

    def as_result(self) -> CliResult:
        """This read as the result a command answers with: the ledger, the verdict, the operation.

        The operation is one this read merely saw rather than one it dispatched, so it is reported
        for a caller to follow and does not decide the exit code.
        """
        return CliResult.succeeded(
            self.ledger, verdict=self.view.verdict, operation=self.view.operation
        )


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
    return read_week(runtime).as_result()


def read_week(runtime: Runtime) -> ReadWeek:
    """The configured week, and the ledger that prints it."""
    view = WeekView.read(runtime.client.read_week(str(runtime.settings.week)))
    return ReadWeek(
        view=view,
        ledger=WeekLedger(week=view, area_names=area_names(runtime.client, runtime.notices)),
    )
