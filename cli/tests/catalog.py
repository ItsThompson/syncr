"""The command catalog, read off the parser rather than listed.

Three suites are stated over "every command": the help each carries, that none of them reads stdin,
and that each answers the wrapper and exits by its own code. Each had its own list, and a list is
exactly what a new command does not join: ticket 50's held four names while the catalog grew to
sixteen, so three guards would have gone on passing over a third of the surface.

Read from the parser because the parser is what a caller reaches. Nothing here knows which commands
exist.
"""

from __future__ import annotations

from syncr_cli.parser import build_parser


def catalog() -> set[tuple[str, str]]:
    """Every command the parser builds, as its own ``(noun, verb)`` pair."""
    found = set()
    for noun, noun_parser in subparsers(build_parser()).items():
        for verb in subparsers(noun_parser):
            found.add((noun, verb))
    return found


def commands() -> list[list[str]]:
    """Every command as the argument list a caller types, in a stable order."""
    return [[noun, verb] for noun, verb in sorted(catalog())]


def subparsers(parser: object) -> dict[str, object]:
    """The child parsers one parser holds, keyed by the word that selects each.

    Reaches argparse's private action list because argparse publishes no accessor for it. That is
    acceptable here and nowhere else: what is under test is the shape of the command line, and the
    alternative is a second list of commands that can disagree with the first.
    """
    for action in getattr(parser, "_actions", []):
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict):
            return choices
    return {}
