"""The service suites' shared fake repositories are declared once, asserted rather than trusted.

A fake repository copied into a second suite drifts from the first: a field added to the record
is then edited once per copy or silently missed by one of them. The settings, Area and Project
fakes each have exactly one home, ``tests/service_fakes.py``, and this census is what keeps
that true: a second declaration anywhere in the test tree reddens here before it can drift.

Like every census here, the helper returns data rather than asserting, so the claim can be
checked by hand against the tree it reads.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

TESTS: Final = Path(__file__).resolve().parent
HOME: Final = "service_fakes.py"

# One declaration each: the fakes every service suite shares. A double that records what it was
# asked is not storage and may live beside the suite whose assertion gives it meaning.
ONE_HOME_FAKES: Final = ("FakeSettingsRepository", "FakeAreaRepository", "FakeProjectRepository")


def declaration_sites(class_name: str) -> list[str]:
    """Every test module declaring ``class_name``, as file names relative to the tests package."""
    sites: list[str] = []
    for path in sorted(TESTS.glob("*.py")):
        tree = ast.parse(path.read_text())
        if any(
            isinstance(node, ast.ClassDef) and node.name == class_name for node in ast.walk(tree)
        ):
            sites.append(path.name)
    return sites


@pytest.mark.parametrize("class_name", ONE_HOME_FAKES)
def test_a_shared_fake_is_declared_only_in_its_home(class_name: str) -> None:
    assert declaration_sites(class_name) == [HOME]
