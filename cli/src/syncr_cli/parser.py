"""The command line: nouns then verbs, and one help text complete enough to work from.

Noun then verb, following ``gh``: ``syncr auth login``, ``syncr week show``.

**Every flag is accepted on either side of the verb.** ``syncr --json week show`` and
``syncr week show --json`` are the same invocation, because a person types one and an agent
generates the other. The shared flags are defined once and attached to both levels with
``SUPPRESS`` as their default, so a flag stated before the verb is not overwritten by the verb's
own absent one.

**A parse failure is this package's error, not the framework's.** ``argparse`` exits 2 and prints
to stderr, which is the right code and the wrong path: the failure has to arrive as a
:class:`~syncr_cli.errors.UsageError` so that ``--json`` still answers with the wrapper an agent
parses. So ``error`` raises.

**Every command's help carries examples and the exit-code table.** An agent needs no external
documentation to orient itself, so the table is printed by ``--help`` on the root and on each
command rather than living in a document.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, NoReturn

from syncr_cli.errors import UsageError
from syncr_cli.exit_codes import exit_code_table
from syncr_cli.idempotency import derive_key, supplied_key
from syncr_cli.settings import (
    DEFAULT_POLL_INTERVAL_MS,
    DEFAULT_TIMEOUT_S,
    Flags,
    OutputFormat,
    environment_variable,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from syncr_cli.results import CliResult
    from syncr_cli.runtime import Runtime

PROGRAM: Final = "syncr"

type Handler = Callable[[Runtime, "Invocation"], CliResult]

# What every parser in the tree writes into the namespace on its own account: the shared flags, and
# the three values the tree itself sets. Named so an invocation's `arguments` can mean "what this
# command declared" rather than "everything argparse produced", and asserted against the shared
# parser's own actions by a test, so the list cannot drift from the flags below.
SHARED_DESTINATIONS: Final = frozenset(
    {
        "api_url",
        "week",
        "output",
        "poll_interval_ms",
        "timeout_s",
        "idempotency_key",
        "help",
    }
)

_TREE_DESTINATIONS: Final = frozenset({"noun", "verb", "handler", "command"})

# The verb table under a noun, and the noun table under the root: argparse builds both with the
# parent's own class, so every parser in the tree refuses in this package's words.
type Verbs = argparse._SubParsersAction["Parser"]

_DESCRIPTION: Final = (
    "The syncr CLI: a deliberate subset of the product for a terminal and for an agent. "
    "It is an OAuth client of the same API the browser uses."
)

_PRECEDENCE: Final = (
    "configuration:\n"
    "  Every setting is read from the first of: the flag, the SYNCR_ environment variable,\n"
    "  ~/.config/syncr/config.toml, the built-in default.\n"
    f"    api_url          {environment_variable('api_url')}\n"
    f"    poll_interval_ms {environment_variable('poll_interval_ms')}  "
    f"default {DEFAULT_POLL_INTERVAL_MS}\n"
    f"    timeout_s        {environment_variable('timeout_s')}  default {DEFAULT_TIMEOUT_S}\n"
    f"    week             {environment_variable('week')}  default the current ISO week\n"
    f"    output           {environment_variable('output')}  "
    "default human on a terminal, json otherwise"
)


@dataclass(frozen=True, slots=True)
class Invocation:
    """What the user asked for, once the command line has been read."""

    command: tuple[str, ...]
    flags: Flags
    arguments: dict[str, object] = field(default_factory=dict)
    stated_idempotency_key: str | None = None

    def value[ValueT](self, name: str, kind: type[ValueT]) -> ValueT | None:
        """One argument this command declared, or ``None`` when the caller stated none.

        ``kind`` is the type the argument's own ``type=`` produces. A value of another type is a
        mistake in this package's declaration of that argument rather than anything a caller can
        cause, so it raises rather than being answered: the traceback names the argument, which is
        what a bug report needs, and the runner deliberately leaves an unexpected exception alone.
        """
        stated = self.arguments.get(name)
        if stated is None:
            return None
        if not isinstance(stated, kind):
            raise TypeError(
                f"{name} was declared to produce {kind.__name__} and arrived as "
                f"{type(stated).__name__}"
            )
        return stated

    def required[ValueT](self, name: str, kind: type[ValueT]) -> ValueT:
        """An argument argparse guaranteed: a positional, or a flag declared ``required``.

        Absent is a mistake in the declaration for the same reason a wrong type is, so it raises.
        """
        stated = self.value(name, kind)
        if stated is None:
            raise TypeError(f"{name} is required and arrived absent")
        return stated

    def idempotency_key(self, arguments: dict[str, object]) -> str:
        """The key a mutation carries: the caller's own, or one derived from this invocation.

        Derived by default so a retry of the same command carries the same key without the caller
        having to remember one, and overridable because an agent batching two identical mutations
        deliberately needs to say that they are two.
        """
        if self.stated_idempotency_key is not None:
            return supplied_key(self.stated_idempotency_key)
        return derive_key(self.command, arguments)


class Parser(argparse.ArgumentParser):
    """An ``ArgumentParser`` whose refusals are this package's errors."""

    def error(self, message: str) -> NoReturn:
        raise UsageError(
            f"{message}. Nothing was changed. Run '{self.prog} --help' for the flags and the "
            "exit-code table."
        )


def parse(argv: Sequence[str]) -> tuple[Invocation, Handler]:
    """Read the command line, or raise the usage error that explains it."""
    parsed = build_parser().parse_args(list(argv))
    handler: Handler | None = getattr(parsed, "handler", None)
    if handler is None:
        raise UsageError(
            f"name a command. Run '{PROGRAM} --help' for the catalog and the exit-code table."
        )
    return (
        Invocation(
            command=tuple(getattr(parsed, "command", ())),
            flags=Flags(
                api_url=getattr(parsed, "api_url", None),
                poll_interval_ms=getattr(parsed, "poll_interval_ms", None),
                timeout_s=getattr(parsed, "timeout_s", None),
                week=getattr(parsed, "week", None),
                output=getattr(parsed, "output", None),
            ),
            arguments=command_arguments(parsed),
            stated_idempotency_key=getattr(parsed, "idempotency_key", None),
        ),
        handler,
    )


def command_arguments(parsed: argparse.Namespace) -> dict[str, object]:
    """Everything the chosen command declared, and nothing the tree or the shared flags did."""
    return {
        name: value
        for name, value in vars(parsed).items()
        if name not in SHARED_DESTINATIONS and name not in _TREE_DESTINATIONS
    }


def build_parser() -> Parser:
    """The whole command line, catalog and all."""
    # Imported here rather than at module scope: a command module reads `Invocation` from this
    # one, so importing them at the top would be a cycle at import time.
    from syncr_cli.commands import auth, backlog, block, day, plan, task, week

    shared = _shared_flags()
    root = Parser(
        prog=PROGRAM,
        description=_DESCRIPTION,
        parents=[shared],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_epilog(
            f"{PROGRAM} auth login",
            f"{PROGRAM} week show --week 2026-W07",
            f"{PROGRAM} plan solve --wait",
            f"{PROGRAM} backlog list --json",
        ),
    )
    nouns = root.add_subparsers(dest="noun", metavar="<noun>")
    for noun in (auth, task, backlog, week, plan, block, day):
        noun.register(nouns, shared)
    return root


def add_verb(
    nouns: Verbs,
    shared: Parser,
    *,
    noun: str,
    noun_help: str,
) -> Verbs:
    """One noun, and the verb table under it.

    ``add_subparsers`` builds its children with the parent's own class, so every parser in the
    tree is a :class:`Parser` and refuses in this package's words without being told to.
    """
    noun_parser = nouns.add_parser(
        noun,
        help=noun_help,
        description=noun_help,
        parents=[shared],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    return noun_parser.add_subparsers(dest="verb", metavar="<verb>")


def register_command(
    verbs: Verbs,
    *,
    noun: str,
    verb: str,
    summary: str,
    handler: Handler,
    shared: Parser,
    examples: tuple[str, ...],
) -> argparse.ArgumentParser:
    """One command, with its own help, its examples, and the exit-code table."""
    command = verbs.add_parser(
        verb,
        help=summary,
        description=summary,
        parents=[shared],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_epilog(*examples),
    )
    command.set_defaults(handler=handler, command=(noun, verb))
    return command


def _epilog(*examples: str) -> str:
    lines = ["examples:", *(f"  {example}" for example in examples), "", _PRECEDENCE, ""]
    return "\n".join([*lines, exit_code_table()])


def _shared_flags() -> Parser:
    """The flags every command takes, defined once.

    ``SUPPRESS`` is the default for all of them, so a flag stated before the verb survives the
    verb's own parse: argparse writes into one namespace, and an absent flag with a real default
    would overwrite the value the root already read.

    A :class:`Parser` rather than a bare ``ArgumentParser`` because it is a parent of every parser
    in the tree, and a tree of one class is what makes every refusal read the same.
    """
    shared = Parser(add_help=False)
    shared.add_argument(
        "--api-url",
        default=argparse.SUPPRESS,
        metavar="URL",
        help="the API to talk to, without a trailing slash",
    )
    shared.add_argument(
        "--week",
        default=argparse.SUPPRESS,
        metavar="ISO_WEEK",
        help="the week to act on, as 2026-W07. Defaults to this machine's current ISO week",
    )
    shared.add_argument(
        "--output",
        default=argparse.SUPPRESS,
        choices=[member.value for member in OutputFormat],
        help="how to write the result. Defaults to human on a terminal and json otherwise",
    )
    shared.add_argument(
        "--json",
        dest="output",
        action="store_const",
        const=OutputFormat.JSON.value,
        default=argparse.SUPPRESS,
        help=f"shorthand for --output {OutputFormat.JSON.value}",
    )
    shared.add_argument(
        "--poll-interval",
        dest="poll_interval_ms",
        type=int,
        default=argparse.SUPPRESS,
        metavar="MS",
        help="how often to poll an operation while waiting, in milliseconds",
    )
    shared.add_argument(
        "--timeout",
        dest="timeout_s",
        type=int,
        default=argparse.SUPPRESS,
        metavar="S",
        help="how long to wait on an operation before exiting 10, in seconds",
    )
    shared.add_argument(
        "--idempotency-key",
        dest="idempotency_key",
        default=argparse.SUPPRESS,
        metavar="KEY",
        help="the key a mutation carries. Derived from the command and its arguments when absent",
    )
    return shared
