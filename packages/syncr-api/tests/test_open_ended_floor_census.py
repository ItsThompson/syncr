"""Every open-ended bump reads the one floor computation, checked mechanically.

``BacklogWideBump.open_ended_range`` is the tree's single expression for "the week holding
today's local date in the home zone". A second derivation anywhere else -- a ``weeks_from``
call fed its own date -- is two services that can disagree about which week a mutation
invalidates, and the disagreement degrades silently as code arrives: what is needed is not
a test of today's modules but a reading that examines whatever modules exist whenever it runs.

Two call sites are sanctioned, each by name:

* ``user_settings/solve_inputs.py``, which owns the expression itself.
* ``user_settings/service.py``, whose home-zone bump cannot take the collaborator because it
  must invalidate exactly the view it resolved before writing; the reason is stated at the
  site, and this file only records that the exemption exists.

The reading reports ``weeks_from`` CALLS and nothing else, so a locally built ``WeekRange``
is not a finding: the bounded shape (``offplan/weeks.py`` and both ``weeks_covering``
callers) constructs ranges of its own deliberately, and forbidding that would forbid the
bounded shape rather than the second floor.

Every helper returns data rather than asserting, so the rule is checked against the real
tree AND against a deliberately planted violation. A census with no positive control passes
forever once it has gone blind, which is worse than having no census at all.

One adjacent reading is deliberately not a finding: ``plans/served_verdicts.py`` resolves
``IsoWeek.containing(local_date(now, profile.home_zone))`` for a single-week verdict read.
That is semantically "the week holding today's local date", but it is not an open-ended bump
floor -- it names no range and bumps nothing -- so the census does not flag it, and this note
is what keeps it from being mistaken for an escaped fourth derivation.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import syncr_api

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

# The one floor computation, and the settings service's stated exemption. Literal prefixes
# rather than values derived from imports, because a guard that derives its allow-list from
# the tree it guards cannot fail when that tree moves.
SHARED_FLOOR_MODULE: Final = "packages/syncr-api/src/syncr_api/user_settings/solve_inputs.py"
EXEMPT_SETTINGS_SERVICE: Final = "packages/syncr-api/src/syncr_api/user_settings/service.py"
SANCTIONED_SITES: Final = frozenset({SHARED_FLOOR_MODULE, EXEMPT_SETTINGS_SERVICE})

# The settings exemption is for the ONE home-zone bump, not the whole file: a second call
# there would be a second floor wearing the exemption, so the file is capped rather than
# exempted wholesale. A legitimate new bump site must widen this budget consciously.
EXEMPT_SITE_BUDGET: Final = 1

FEATURE_ROOTS: Final = ("packages/*/src", "cli/src")

# The total-collapse control: below this count the walk has stopped measuring the repository
# and every finding (or absence) is empty by construction rather than by fact.
MODULES_FLOOR: Final = 300


@dataclass(frozen=True, slots=True)
class Site:
    """One ``weeks_from`` call, and the module that made it."""

    module: str
    call: str


def repository_root() -> Path:
    """The checkout the imported package came from, which is the tree every scan below reads."""
    return Path(syncr_api.__file__).resolve().parents[4]


def feature_modules(root: Path) -> Mapping[str, Path]:
    """Every Python file under the feature roots, keyed on path relative to ``root``."""
    found: dict[str, Path] = {}
    for pattern in FEATURE_ROOTS:
        for source_root in sorted(root.glob(pattern)):
            for path in sorted(source_root.rglob("*.py")):
                found[str(path.relative_to(root))] = path
    return found


def weeks_from_calls(source: str, *, module: str) -> tuple[Site, ...]:
    """Every ``weeks_from`` call in this source, however the name was bound.

    A bare-name call matches even without an import, because the shared floor's own module
    calls the function it defines; an aliased import resolves to the same finding, which is
    exactly the shape a quiet second floor would take. An attribute call
    (``solve_inputs.weeks_from(...)``) matches on the attribute alone, which over-matches only
    a same-named method of some other object; no such object ships, and a false positive here
    is adjudication, not blindness.
    """
    tree = ast.parse(source)
    aliases = frozenset({"weeks_from", *_aliases_of_weeks_from(tree)})
    return tuple(
        Site(module, ast.unparse(node))
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id in aliases)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "weeks_from")
        )
    )


def violations(root: Path) -> tuple[Site, ...]:
    """Every ``weeks_from`` call outside the sanctioned sites, across the whole tree."""
    found: list[Site] = []
    for relative, path in feature_modules(root).items():
        if relative in SANCTIONED_SITES:
            continue
        found.extend(weeks_from_calls(path.read_text(), module=relative))
    return tuple(found)


def all_call_sites(root: Path) -> Mapping[str, tuple[Site, ...]]:
    """Every module's ``weeks_from`` calls, including the sanctioned ones."""
    return {
        relative: weeks_from_calls(path.read_text(), module=relative)
        for relative, path in feature_modules(root).items()
    }


def _aliases_of_weeks_from(tree: ast.AST) -> Iterator[str]:
    """The local names this module binds ``weeks_from`` to."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for name in node.names:
                if name.name == "weeks_from":
                    yield name.asname or name.name


# ---------------------------------------------------------------------------------
# The readings against the real tree
# ---------------------------------------------------------------------------------


def test_the_walk_reads_the_checkout_whose_code_this_file_imports() -> None:
    # The scans resolve the tree from the imported package while the sanctioned set describes
    # paths in this checkout, so a run against a scratch copy could otherwise derive one
    # answer from the copy and one from the original.
    assert repository_root() == Path(__file__).resolve().parents[3]


def test_the_walk_finds_the_feature_tree_and_excludes_the_tests() -> None:
    found = feature_modules(repository_root())

    assert len(found) > MODULES_FLOOR
    assert SHARED_FLOOR_MODULE in found
    assert not [module for module in found if "/tests/" in module]


def test_every_weeks_from_call_sits_behind_the_shared_floor_or_the_settings_service() -> None:
    assert violations(repository_root()) == ()


def test_the_census_has_not_gone_blind_over_the_real_tree() -> None:
    # Both sanctioned sites still call ``weeks_from`` today. If either stopped, the exemption
    # above describes a site that no longer exists, and the census would be passing over a
    # narrowed surface without anyone deciding to narrow it.
    sites = all_call_sites(repository_root())

    assert sites[SHARED_FLOOR_MODULE], "the shared floor no longer calls weeks_from"
    assert sites[EXEMPT_SETTINGS_SERVICE], "the exempt settings site no longer calls weeks_from"


def test_the_settings_exemption_covers_one_call_not_the_whole_file() -> None:
    # The exemption names the home-zone bump, so a SECOND weeks_from elsewhere in the file is
    # a second floor wearing the exemption rather than a sanctioned site. Capping the count
    # closes that hole without pinning the guard to a method name a rename would break.
    sites = all_call_sites(repository_root())

    assert len(sites[EXEMPT_SETTINGS_SERVICE]) == EXEMPT_SITE_BUDGET


# ---------------------------------------------------------------------------------
# The positive controls: synthetic source, and a violation planted in a tree
# ---------------------------------------------------------------------------------


def test_a_direct_call_outside_the_sanctioned_sites_is_reported() -> None:
    source = (
        "from syncr_api.user_settings.solve_inputs import weeks_from\n"
        "\n"
        "def floor(today):\n"
        "    return weeks_from(today)\n"
    )

    assert weeks_from_calls(
        source, module="packages/syncr-api/src/syncr_api/habits/service.py"
    ) == (
        Site(
            "packages/syncr-api/src/syncr_api/habits/service.py",
            "weeks_from(today)",
        ),
    )


def test_an_aliased_call_is_reported_under_its_alias() -> None:
    source = (
        "from syncr_api.user_settings.solve_inputs import weeks_from as wf\n"
        "\n"
        "span = wf(date.today())\n"
    )

    assert len(weeks_from_calls(source, module="synthetic")) == 1


def test_a_locally_built_week_range_is_not_a_violation() -> None:
    # The bounded shape builds ranges of its own; only a second ``weeks_from`` call would be
    # a second floor. This is what keeps the census from forbidding the legitimate shape.
    source = (
        "from syncr_api.user_settings.solve_inputs import WeekRange\n"
        "range = WeekRange(first=week, last=None)\n"
    )

    assert weeks_from_calls(source, module="synthetic") == ()


def test_a_planted_module_in_a_feature_tree_is_reported(tmp_path: Path) -> None:
    # The positive control over a whole walk, not just a parser: a file that does not exist
    # yet, planted where a feature module ships, must be found by the same reading that
    # clears the real checkout.
    planted = tmp_path / "packages" / "syncr-api" / "src" / "syncr_api" / "habits" / "service.py"
    planted.parent.mkdir(parents=True)
    planted.write_text(
        "from syncr_api.user_settings.solve_inputs import weeks_from\n"
        "\n"
        "def bump(today):\n"
        "    return weeks_from(today)\n",
        encoding="utf-8",
    )

    assert violations(tmp_path) == (Site(str(planted.relative_to(tmp_path)), "weeks_from(today)"),)
