"""The published CLI reference, asserted against the code it documents.

``docs/cli.md`` exists so a reader needs no checkout to learn the surface, which makes it a
second statement of facts the code owns. A second statement drifts silently unless something
compares them, so this module does: the exit-code table against :class:`ExitCode`, and the
command catalog against the parser itself. The doc may say more than the code; it may never
say otherwise.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from syncr_cli.exit_codes import ExitCode
from tests.catalog import catalog

REFERENCE_PATH = Path(__file__).resolve().parents[2] / "docs" / "cli.md"


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
