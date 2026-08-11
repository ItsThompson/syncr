"""Where the stored write-target role can come from, derived from the tree rather than listed.

A rule that refuses an unwritable calendar is worth what its placement is worth: applied on one
path, it is a rule the tree can grow a second path around, and the second path stores a role the
first one would have refused. So the paths are DERIVED here, from every shipped module's syntax
tree, and the declared sets below are what a new one is adjudicated against.

Two readings, because a bypass has two shapes:

* a **role write**: a call keyword named ``role``, or an assignment to an attribute named ``role``.
  Every ORM write and every dataclass replacement takes one of those two forms.
* a **naming**: a site that names the ``WRITE_TARGET`` constant or spells its value. Reading the
  role is not writing it, so a naming is not a finding by itself; the declared set is what makes a
  new site visible to whoever adds it.

What neither reading covers, stated so the gap is not mistaken for a guarantee: the value spelled
inside a longer SQL string, as ``op.execute("UPDATE ... SET role='write-target'")`` would. These
scans read code, not SQL. Two such spellings exist today, both in ``alembic/versions``'s
``0007_calendar_sources``: the partial unique index's predicate and the role check constraint. Both
are DDL and neither writes a row, so the one-write answer below holds. A migration that backfilled
the column that way would pass here, and what would catch it is a reading of the migration chain,
which no test does yet.

Every helper returns data rather than asserting, so each rule is checked against the real tree AND
against synthetic source. A scan that has quietly stopped finding anything otherwise passes forever.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import syncr_api
from syncr_api.calendars.config import WRITE_TARGET

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

# The field on the row, and the name the one sanctioned spelling of its write-target value carries.
ROLE_FIELD: Final = "role"
ROLE_CONSTANT: Final = "WRITE_TARGET"

# The roots holding code that could reach the table: every package's shipped source, the CLI, the
# migration chain, and the operational scripts that run against a deployed database.
SHIPPED_ROOTS: Final = (
    "packages/*/src",
    "cli/src",
    "packages/syncr-api/alembic",
    "deployments/ops",
)

# Below this, the walk has stopped measuring the repository and every set derived from it is empty
# by construction rather than by fact.
MODULES_FLOOR: Final = 300

# The trees the walk must reach, declared as literal prefixes rather than read back out of
# SHIPPED_ROOTS, because a guard derived from the thing it guards cannot fail when that thing
# narrows. Every package rather than a sample of them: a glob narrowed to a subset, and a filter
# applied inside the walk, are two different collapses and neither is visible from the roots alone.
PACKAGE_TREES: Final = (
    "packages/syncr-api/src/",
    "packages/syncr-common/src/",
    "packages/syncr-domain/src/",
    "packages/syncr-learning/src/",
    "packages/syncr-solver/src/",
)
COVERED_TREES: Final = (
    *PACKAGE_TREES,
    "cli/src/",
    "packages/syncr-api/alembic/",
    "deployments/ops/",
)


@dataclass(frozen=True, slots=True)
class Site:
    """One place in the shipped tree, and what it wrote or named there."""

    module: str
    scope: str
    written: str


def repository_root() -> Path:
    """The checkout the imported package came from, which is the tree every scan below reads."""
    return Path(syncr_api.__file__).resolve().parents[4]


def shipped_modules(root: Path) -> Mapping[str, Path]:
    """Every Python file this repository ships, by path relative to the root. Tests are not shipped.

    Keyed on the relative path rather than on an import path, because the migration chain and the
    operational scripts are not importable as members of a package and would collide.
    """
    found: dict[str, Path] = {}
    for shipped in SHIPPED_ROOTS:
        for source_root in sorted(root.glob(shipped)):
            for path in sorted(source_root.rglob("*.py")):
                found[str(path.relative_to(root))] = path
    return found


def role_writes(source: str, *, module: str) -> tuple[Site, ...]:
    """Every site in this module that puts a value in a ``role`` field, with the value as written.

    The value is unparsed rather than evaluated, so a write of the constant, a write of a literal
    and a write of whatever the caller passed are three distinct answers rather than one.
    """
    found: list[Site] = []
    for node, scope in _scoped(source):
        if isinstance(node, ast.keyword) and node.arg == ROLE_FIELD:
            found.append(Site(module, scope, ast.unparse(node.value)))
        elif isinstance(node, ast.Assign):
            found.extend(
                Site(module, scope, ast.unparse(node.value))
                for target in node.targets
                if isinstance(target, ast.Attribute) and target.attr == ROLE_FIELD
            )
    return tuple(found)


def role_namings(source: str, *, module: str) -> tuple[Site, ...]:
    """Every site naming the write-target constant, or spelling its value as a whole string.

    Equality on the string rather than containment, because the value appears inside the prose of
    several docstrings and inside the index predicate the model builds from the constant. A site
    that spells it as a bare literal is the divergence worth seeing.
    """
    return tuple(
        Site(module, scope, ast.unparse(node))
        for node, scope in _scoped(source)
        if (isinstance(node, ast.Name) and node.id == ROLE_CONSTANT)
        or (isinstance(node, ast.Constant) and node.value == WRITE_TARGET)
    )


def method_calls(source: str, *, named: str, module: str) -> tuple[Site, ...]:
    """Every call of a method of this exact name, with the receiver as written.

    Exact equality on the attribute, so a method whose name merely begins with this one is a
    different method rather than a match.
    """
    return tuple(
        Site(module, scope, ast.unparse(node.func.value))
        for node, scope in _scoped(source)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == named
    )


def _scoped(source: str) -> Iterator[tuple[ast.AST, str]]:
    """Every node of this source, paired with the dotted class-and-function it sits inside.

    Recursive rather than a flat walk, because attribution is the point: a write inside a method of
    a class has to name both, and a write at module level has to be distinguishable from one in a
    function.
    """
    yield from _within(ast.parse(source), "")


def _within(node: ast.AST, scope: str) -> Iterator[tuple[ast.AST, str]]:
    for child in ast.iter_child_nodes(node):
        nested = scope
        if isinstance(child, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            nested = f"{scope}.{child.name}" if scope else child.name
        yield child, nested
        yield from _within(child, nested)


# --------------------------------------------------------------------------------
# The controls: that the walk reads this checkout, and that the scans still find things
# --------------------------------------------------------------------------------


def test_the_walk_reads_the_checkout_whose_code_this_file_imports() -> None:
    # The control for every derivation below. The scans resolve a tree from the imported package
    # while the sets they are asserted against describe imported behaviour, so a run against a
    # scratch copy could otherwise derive one answer from the copy and one from the original.
    assert repository_root() == Path(__file__).resolve().parents[3]


def test_the_walk_finds_the_shipped_tree_and_excludes_the_tests() -> None:
    found = shipped_modules(repository_root())

    assert len(found) > MODULES_FLOOR
    assert "packages/syncr-api/src/syncr_api/calendars/repository.py" in found
    assert not [module for module in found if "/tests/" in module]


def test_the_walk_reaches_every_tree_the_role_could_be_stored_from() -> None:
    # The floor above is a total-collapse control and nothing more: every declared site lives under
    # one of these trees, so dropping any of the others leaves all four exact sets intact and the
    # count still far above the floor. This is what makes a NARROWED walk visible.
    found = shipped_modules(repository_root())

    reached = {
        tree: [module for module in found if module.startswith(tree)] for tree in COVERED_TREES
    }

    assert {tree: bool(modules) for tree, modules in reached.items()} == dict.fromkeys(
        COVERED_TREES, True
    )


def test_the_walk_reaches_the_packages_the_repository_holds_and_no_others() -> None:
    # Stated over the answer rather than over the roots, because a package can be lost two ways: a
    # glob narrowed to a subset, and a filter inside the walk that the roots never see. Both change
    # this set. A package ADDED to the repository also changes it, which is the adjudication a new
    # tree owes: whether it can store the role is a question, not a default.
    found = shipped_modules(repository_root())

    reached = {
        module.split("/src/")[0] + "/src/"
        for module in found
        if module.startswith("packages/") and "/src/" in module
    }

    assert reached == set(PACKAGE_TREES)


def test_a_role_write_is_found_wherever_it_sits() -> None:
    # The nesting control. Attribution walks the tree, so a write inside an async method of a class
    # has to be attributed to both, and a write at module level to neither.
    source = (
        "row.role = WRITE_TARGET\n"
        "class Repo:\n"
        "    async def promote(self):\n"
        "        await self.session.execute(update(Row).values(role=WRITE_TARGET))\n"
    )

    assert role_writes(source, module="synthetic") == (
        Site("synthetic", "", ROLE_CONSTANT),
        Site("synthetic", "Repo.promote", ROLE_CONSTANT),
    )


def test_reading_the_role_is_not_writing_it() -> None:
    # The other side of the same control: a scan that reported comparisons would report the readers
    # of the role as sites that store it, and the declared set below would say nothing.
    source = (
        "def held(rows):\n"
        "    return [row for row in rows if row.role == WRITE_TARGET]\n"
        "def bound(row):\n"
        "    return row.role != WRITE_TARGET or row.horizon_days\n"
    )

    assert role_writes(source, module="synthetic") == ()


def test_a_naming_inside_prose_is_not_a_naming_in_code() -> None:
    source = '"""The write-target role, stored as write-target."""\nrole = WRITE_TARGET\n'

    assert role_namings(source, module="synthetic") == (Site("synthetic", "", ROLE_CONSTANT),)


def test_a_bare_spelling_of_the_value_is_a_naming() -> None:
    # A site that spells the value rather than reading the constant is the divergence risk the
    # second arm exists for: the constant is what the model's own check constraint is built from.
    source = "def promote(row):\n    row.role = 'write-target'\n"

    assert role_namings(source, module="synthetic") == (
        Site("synthetic", "promote", repr(WRITE_TARGET)),
    )


def test_a_method_call_is_matched_on_the_whole_name() -> None:
    # A name that is a prefix of another is the anchoring hazard here: `designate_write_target` and
    # `designate_write_target_later` are two methods, and a containment test would conflate them.
    source = (
        "async def route(service):\n"
        "    await service.designate_write_target(one)\n"
        "    await service.designate_write_target_later(one)\n"
    )

    assert method_calls(source, named="designate_write_target", module="synthetic") == (
        Site("synthetic", "route", "service"),
    )


# --------------------------------------------------------------------------------
# The rule: one path stores the role, and it is reached through the service that refuses
# --------------------------------------------------------------------------------

# Every site in the shipped tree that puts a value in a `role` field, and what it puts there.
#
# The write-target value is written in exactly one place, which is what makes the rules applied
# before that call the rules that govern the role. The other four write no such value: `create`
# writes whatever its caller passed, and its one caller passes the anchor-source constant, because
# adding a calendar and handing syncr destructive write access to it are two acts the user takes
# separately; the last two carry a row's stored role outward into a record and into a response.
DECLARED_ROLE_WRITES: Final = {
    Site(
        "packages/syncr-api/src/syncr_api/calendars/repository.py",
        "CalendarSourceRepository.designate_write_target",
        ROLE_CONSTANT,
    ),
    Site(
        "packages/syncr-api/src/syncr_api/calendars/repository.py",
        "CalendarSourceRepository.create",
        ROLE_FIELD,
    ),
    Site(
        "packages/syncr-api/src/syncr_api/calendars/repository.py",
        "_as_record",
        "cast('CalendarRole', row.role)",
    ),
    Site(
        "packages/syncr-api/src/syncr_api/calendars/schemas.py",
        "CalendarSourceResponse.of",
        "record.role",
    ),
    Site(
        "packages/syncr-api/src/syncr_api/calendars/service.py",
        "CalendarSourceService.add_source",
        "ANCHOR_SOURCE",
    ),
}

# Where the one write-target write is reached from. The route reaches the service, the service
# reaches the repository, and the rules in `calendars/rules.py` are applied in between.
DECLARED_CALLERS: Final = {
    Site(
        "packages/syncr-api/src/syncr_api/calendars/api.py",
        "designate_write_target",
        "service",
    ),
    Site(
        "packages/syncr-api/src/syncr_api/calendars/service.py",
        "CalendarSourceService.designate_write_target",
        "self._sources",
    ),
}


# Which shipped code names the role at all, and every member reads it: the config declares it, the
# model builds its index and its check constraint from it, the repository writes it and selects on
# it, and the service, the schemas and the horizon rule compare against it.
DECLARED_NAMINGS: Final = {
    ("packages/syncr-api/src/syncr_api/calendars/config.py", ""),
    ("packages/syncr-api/src/syncr_api/calendars/models.py", "CalendarSource"),
    (
        "packages/syncr-api/src/syncr_api/calendars/repository.py",
        "CalendarSourceRepository.write_target",
    ),
    (
        "packages/syncr-api/src/syncr_api/calendars/repository.py",
        "CalendarSourceRepository.designate_write_target",
    ),
    ("packages/syncr-api/src/syncr_api/calendars/rules.py", "require_the_write_target"),
    (
        "packages/syncr-api/src/syncr_api/calendars/service.py",
        "CalendarSourceService.designate_write_target",
    ),
    ("packages/syncr-api/src/syncr_api/calendars/schemas.py", "WriteTargetResponse.of"),
}


def test_every_role_write_in_the_shipped_tree_is_declared() -> None:
    found = {
        site
        for module, path in shipped_modules(repository_root()).items()
        for site in role_writes(path.read_text(encoding="utf-8"), module=module)
    }

    assert found == DECLARED_ROLE_WRITES


def test_the_write_target_role_is_written_in_one_place() -> None:
    found = {
        site
        for module, path in shipped_modules(repository_root()).items()
        for site in role_writes(path.read_text(encoding="utf-8"), module=module)
        if site.written == ROLE_CONSTANT
    }

    assert len(found) == 1
    assert found <= DECLARED_ROLE_WRITES


def test_every_caller_of_the_designation_is_declared() -> None:
    found = {
        site
        for module, path in shipped_modules(repository_root()).items()
        for site in method_calls(
            path.read_text(encoding="utf-8"), named="designate_write_target", module=module
        )
    }

    assert found == DECLARED_CALLERS


def test_every_site_naming_the_write_target_role_is_declared() -> None:
    # Not filtered to the calendars package: a naming anywhere else in the shipped tree fails this,
    # which is what makes a second package that stores the role visible here.
    found = {
        (site.module, site.scope)
        for module, path in shipped_modules(repository_root()).items()
        for site in role_namings(path.read_text(encoding="utf-8"), module=module)
    }

    assert found == DECLARED_NAMINGS
