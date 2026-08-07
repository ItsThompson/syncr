"""``backlog list``: the outstanding work, with the at-risk figure the server determined.

The same read as ``task list`` and a different question. ``task list`` answers "what tasks are
there", so it takes ``--status`` and imposes none. The backlog is what is still owed, so it asks for
the open work unless the caller states otherwise, and it is the surface the at-risk figure belongs
on.

**The at-risk figure is read, never computed.** A task is at risk when the feasibility probe reports
a deadline shortfall naming it, so it is the verdict's determination. A client that compared a
deadline against a capacity of its own would be a second arithmetic, and a task would then be at
risk on one surface and fine on another. ``--at-risk`` narrows the list for the same reason it does
not filter the rows here: the parameter reaches the route that makes the determination.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_cli.commands.task import filter_arguments, read_backlog
from syncr_cli.parser import add_verb, register_command
from syncr_cli.results import CliResult

if TYPE_CHECKING:
    from syncr_cli.parser import Invocation, Parser, Verbs
    from syncr_cli.runtime import Runtime

NOUN = "backlog"

# What the backlog is, unless the caller names another status: the work still owed.
OPEN = "open"


def register(nouns: Verbs, shared: Parser) -> None:
    """Put the backlog command in the catalog."""
    verbs = add_verb(nouns, shared, noun=NOUN, noun_help="Read the backlog")
    listing = register_command(
        verbs,
        noun=NOUN,
        verb="list",
        summary=(
            "The backlog: the open work, and how many tasks the current verdict reports a deadline "
            "shortfall for"
        ),
        handler=listed,
        shared=shared,
        examples=(
            "syncr backlog list",
            "syncr backlog list --at-risk",
            "syncr backlog list --area <area-id>",
            "syncr backlog list --json | jq '.data.header.atRiskCount'",
        ),
    )
    # The same three filters ``task list`` takes, from the same declaration: two spellings of one
    # argument is how this one came to accept a whitespace-only Area that the other refuses.
    filter_arguments(listing, status_help=f"read another status instead of the '{OPEN}' work")


def listed(runtime: Runtime, invocation: Invocation) -> CliResult:
    """Read the open work and the counts the server computed for it."""
    return CliResult.succeeded(read_backlog(runtime, invocation, status=OPEN))
