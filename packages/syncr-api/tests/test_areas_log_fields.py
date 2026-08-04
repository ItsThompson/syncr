"""No field these modules log is bound under a name the redactor eats.

Two rules meet in one line of source, and getting either wrong is silent.

The redactor treats ``name`` as user CONTENT and eats it exactly or as a ``_`` suffix, so an
``area_name`` would render as ``[redacted]``: the line would survive and say nothing. And an
Area's name genuinely IS content, so logging one would disclose as much as a block title does.
The two rules point the same way, which is why the fix is the same one: log the identifier.

Stated over every module of the packages named below, by reading the source for the keywords each
logging call binds, so a module added to one of them comes under the rule without this file being
edited. The
question is asked of the redactor's own predicate rather than of a list of names copied from it,
so a rename over there is caught here rather than in a log nobody is reading at the time.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

import pytest

from syncr_common.logging import is_sensitive_key

if TYPE_CHECKING:
    from pathlib import Path

# The packages this rule is stated over. Each logs an identifier for a row whose name, title, or
# location is the user's own words, so each has the same way of getting this wrong. Append a package
# here when it starts logging; the rule then reads every module of it without further editing.
PACKAGES = (
    "areas",
    "budgets",
    "calendars",
    "google_account",
    "habits",
    "offplan",
    "routines",
    "tasks",
    "templates",
)

# structlog's own levels. A call to any of them binds fields.
LOG_METHODS = frozenset({"debug", "info", "warning", "error", "critical", "exception"})


def logged_keywords(source: str) -> list[str]:
    """Every keyword name a logging call in this source binds.

    Matched on the method name whatever the receiver, because the logger is held in a module
    local and no import alias can resolve a method on one.
    """
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in LOG_METHODS:
            continue
        found.extend(keyword.arg for keyword in node.keywords if keyword.arg is not None)
    return sorted(found)


def package_sources(source_root: Path, package: str) -> list[Path]:
    return sorted((source_root / package).glob("*.py"))


def test_the_walk_finds_the_lines_these_packages_actually_emit(source_root: Path) -> None:
    # The control. Every assertion below iterates over what the walk found, so on a walk that
    # found nothing they would all pass while proving nothing.
    bound = [
        keyword
        for package in PACKAGES
        for module in package_sources(source_root, package)
        for keyword in logged_keywords(module.read_text(encoding="utf-8"))
    ]

    assert "tenant_id" in bound
    assert "area_id" in bound


@pytest.mark.parametrize("package", PACKAGES)
def test_no_logged_field_is_bound_under_a_name_the_redactor_eats(
    source_root: Path, package: str
) -> None:
    modules = package_sources(source_root, package)
    assert modules, f"no module was found under {source_root / package}"

    eaten = {
        module.name: [
            keyword
            for keyword in logged_keywords(module.read_text(encoding="utf-8"))
            if is_sensitive_key(keyword)
        ]
        for module in modules
    }

    assert {name: keys for name, keys in eaten.items() if keys} == {}, (
        f"{eaten} render as [redacted] rather than as their value. Log the identifier: an "
        "Area's or a Project's name is the user's own words, so the redactor is right to eat "
        "it and the line has to carry something else."
    )


@pytest.mark.parametrize(
    ("source", "eaten"),
    [
        ('_log.info("areas.area.declared", area_name="Job search")', ["area_name"]),
        ('_log.info("areas.area.declared", name="Job search")', ["name"]),
        ('_log.warning("areas.area.refused", description="a note")', ["description"]),
        ('_log.info("areas.area.declared", area_id="1")', []),
        ('service.info("not a logger", name="fine")', ["name"]),
    ],
    ids=["a suffixed name", "a bare name", "another content key", "an identifier", "any receiver"],
)
def test_the_reading_reports_a_field_the_redactor_would_eat(source: str, eaten: list[str]) -> None:
    # The other half of the control: the rule has to distinguish rather than flag every keyword,
    # and it has to see a logging call whatever the logger is called at the call site.
    assert [key for key in logged_keywords(source) if is_sensitive_key(key)] == eaten
