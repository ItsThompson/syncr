"""The published CLI reference, asserted against the code it documents.

``docs/cli.md`` exists so a reader needs no checkout to learn the surface, which makes it a
second statement of facts the code owns. A second statement drifts silently unless something
compares them, so this module does: the exit-code table against :class:`ExitCode`, and the
command catalog against the parser itself. The doc may say more than the code; it may never
say otherwise.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from syncr_cli.exit_codes import ExitCode
from syncr_cli.parser import build_parser
from tests.catalog import catalog, subparsers

REFERENCE_PATH = Path(__file__).resolve().parents[2] / "docs" / "cli.md"

# The option strings the reference documents once, in its shared-flags table, because the parser
# attaches them to every command: per-command rows state only what the command adds.
SHARED_OPTIONS = frozenset(
    {
        "--api-url",
        "--week",
        "--output",
        "--json",
        "--poll-interval",
        "--timeout",
        "--idempotency-key",
    }
)


def reference() -> str:
    return REFERENCE_PATH.read_text(encoding="utf-8")


def exit_code_section() -> list[str]:
    """The lines of the reference's exit-code section, where its table lives."""
    lines = reference().splitlines()
    start = lines.index("## Exit codes")
    end = lines.index("## Command catalog")
    return lines[start:end]


@pytest.mark.parametrize("code", list(ExitCode))
def test_every_code_has_the_row_its_summary_states(code: ExitCode) -> None:
    row = rf"^\| {code.value} \| {re.escape(code.summary)} \|$"
    assert any(re.match(row, line) for line in exit_code_section()), (
        f"{code.value} is missing or misstated in {REFERENCE_PATH.name}"
    )


def test_the_reference_lists_no_code_the_enum_does_not_hold() -> None:
    stated = {
        int(match.group(1))
        for line in exit_code_section()
        if (match := re.match(r"^\| (\d+) \| ", line))
    }
    assert stated == {int(code) for code in ExitCode}


@pytest.mark.parametrize("noun_verb", sorted(catalog()))
def test_every_command_is_named_in_the_reference(noun_verb: tuple[str, str]) -> None:
    # The backtick is left open on purpose: a row may continue into positional arguments,
    # as `syncr task add TITLE` does.
    assert f"`syncr {noun_verb[0]} {noun_verb[1]}" in reference(), (
        f"{noun_verb[0]} {noun_verb[1]} is missing from {REFERENCE_PATH.name}"
    )


@pytest.mark.parametrize("noun_verb", sorted(catalog()))
def test_every_command_row_states_the_flags_the_parser_declares(
    noun_verb: tuple[str, str],
) -> None:
    parser = command_parsers()[noun_verb]
    row = command_rows()[noun_verb]
    for flag in declared_options(parser):
        # The closing backtick is left open: a row writes the flag with its value spelled out,
        # as `--area AREA_ID` does.
        assert f"`{flag}" in row, f"{noun_verb[0]} {noun_verb[1]} omits {flag}"
    for argument in declared_positionals(parser):
        assert argument in row, f"{noun_verb[0]} {noun_verb[1]} omits its {argument} argument"


def command_parsers() -> dict[tuple[str, str], argparse.ArgumentParser]:
    """Every command's own parser, keyed by its ``(noun, verb)`` pair."""
    found = {}
    for noun, noun_parser in subparsers(build_parser()).items():
        for verb, verb_parser in subparsers(noun_parser).items():
            # add_subparsers builds children with the parent's own class, so each is a Parser.
            assert isinstance(verb_parser, argparse.ArgumentParser)
            found[(noun, verb)] = verb_parser
    return found


def command_rows() -> dict[tuple[str, str], str]:
    """The one catalog line naming each command, where that command's flags are stated."""
    lines = reference().splitlines()
    return {
        (noun, verb): next(
            line
            for line in lines
            if line.startswith((f"| `syncr {noun} {verb}`", f"| `syncr {noun} {verb} "))
        )
        for noun, verb in catalog()
    }


def declared_options(parser: argparse.ArgumentParser) -> list[str]:
    """The options a command adds beyond the shared set, long spelling only."""
    return [
        option
        for action in parser._actions
        if not set(action.option_strings) & SHARED_OPTIONS
        for option in action.option_strings
        if option not in {"-h", "--help"}
    ]


def declared_positionals(parser: argparse.ArgumentParser) -> list[str]:
    """The positional arguments a command takes, named as the reference spells them."""
    return [
        getattr(action, "metavar", None) or action.dest.upper()
        for action in parser._actions
        if not action.option_strings and action.nargs != 0
    ]
