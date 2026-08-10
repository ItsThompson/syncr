"""The rule that the refused address ranges are stated in one place, and the sites an address
passes through on its way to storage.

Two claims, both about the code rather than about its behavior, and both enforceable only by a
test that reads the package.

**The ranges are stated once.** The scan reads every module for the three mechanisms that can
express an address range and requires that exactly one module uses any of them. Two statements
of a range set is how an accept-list and a redirect check come to disagree, and the
disagreement is invisible while both are green.

**A feed address is normalized at one site, and every site that admits one is accounted for.**
Putting the refusal in the normalizer is only sound while there is one place a pasted address
becomes a stored one. That is a claim about the package, so it is derived from the package.

Every rule here is driven against hand-written sources as well as against the real tree: a scan
with no positive control passes forever once the mechanism it looks for has been renamed.
"""

from __future__ import annotations

import ast
import re
from ipaddress import ip_network
from typing import TYPE_CHECKING, Final

import pytest

from tests.boundaries import imported_modules

if TYPE_CHECKING:
    from pathlib import Path

PREDICATE_MODULE = "calendars.addresses"
RANGE_LIBRARY = "ipaddress"

# The library's own names for the ranges. A second module deciding whether an address may be
# fetched reads one of these, and reading one is what this scan calls a statement of the ranges.
CLASSIFYING_PROPERTIES: Final = frozenset(
    {
        "ipv4_mapped",
        "is_global",
        "is_link_local",
        "is_loopback",
        "is_multicast",
        "is_private",
        "is_reserved",
        "is_site_local",
        "is_unspecified",
        "sixtofour",
        "teredo",
    }
)

IMPORTS_THE_LIBRARY: Final = "imports the address library"
STATES_A_NETWORK: Final = "states an address range"
READS_A_CLASSIFYING_PROPERTY: Final = "reads a range-classifying property"

# A prefixed network in any spelling a source file could hold one. Deliberately wider than a
# valid network: what a token means is decided by parsing it, not by the pattern.
NETWORK_SHAPED = re.compile(r"[0-9A-Fa-f:.]+/\d{1,3}")

POSITIVE_CONTROLS: Final = (
    ("import ipaddress\n", IMPORTS_THE_LIBRARY),
    ("from ipaddress import ip_address\n", IMPORTS_THE_LIBRARY),
    ("REFUSED = ('10.0.0.0/8', '172.16.0.0/12')\n", STATES_A_NETWORK),
    ("INSIDE = 'fc00::/7'\n", STATES_A_NETWORK),
    ("def refuse(address):\n    return address.is_private\n", READS_A_CLASSIFYING_PROPERTY),
    ("def refuse(a):\n    return a.ipv4_mapped is not None\n", READS_A_CLASSIFYING_PROPERTY),
)


def statements_of_the_ranges(source: str) -> set[str]:
    """Which of the three mechanisms for expressing an address range this source uses."""
    found: set[str] = set()
    if RANGE_LIBRARY in imported_modules(source):
        found.add(IMPORTS_THE_LIBRARY)
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and node.attr in CLASSIFYING_PROPERTIES:
            found.add(READS_A_CLASSIFYING_PROPERTY)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found |= {STATES_A_NETWORK} if _holds_a_network(node.value) else set()
    return found


def _holds_a_network(text: str) -> bool:
    for token in NETWORK_SHAPED.findall(text):
        try:
            ip_network(token)
        except ValueError:
            continue
        return True
    return False


def module_name(path: Path, source_root: Path) -> str:
    return ".".join(path.relative_to(source_root).with_suffix("").parts)


def modules_by_statement(source_root: Path) -> dict[str, set[str]]:
    """Every module of the package that states a range, and which mechanisms it used."""
    found: dict[str, set[str]] = {}
    for path in sorted(source_root.rglob("*.py")):
        statements = statements_of_the_ranges(path.read_text(encoding="utf-8"))
        if statements:
            found[module_name(path, source_root)] = statements
    return found


@pytest.mark.parametrize(
    ("source", "expected"), POSITIVE_CONTROLS, ids=[expected for _, expected in POSITIVE_CONTROLS]
)
def test_the_scan_finds_each_mechanism_for_stating_a_range(source: str, expected: str) -> None:
    # The positive control. Renaming the mechanism the scan looks for would otherwise leave it
    # green over a package that had come to state its ranges in four places.
    assert expected in statements_of_the_ranges(source)


def test_a_source_that_states_no_range_is_not_reported() -> None:
    assert statements_of_the_ranges("HOST = 'example.com'\nPORT = 8443\n") == set()
    # A bare address is not a range statement: a module may name one host of its own without
    # owning the question of which ranges are refused.
    assert statements_of_the_ranges("HOST = '127.0.0.1'\n") == set()


def test_the_refused_ranges_are_stated_in_exactly_one_module(source_root: Path) -> None:
    # Equality, not membership. A subset check passes just as happily when the owning module has
    # stopped stating the ranges at all, which is the failure this rule cannot afford.
    assert set(modules_by_statement(source_root)) == {PREDICATE_MODULE}


def test_the_one_module_uses_every_mechanism_the_scan_looks_for(source_root: Path) -> None:
    # What makes the equality above meaningful: the owning module trips all three signals, so the
    # scan is armed against the package itself rather than against the controls alone.
    assert modules_by_statement(source_root)[PREDICATE_MODULE] == {
        IMPORTS_THE_LIBRARY,
        STATES_A_NETWORK,
        READS_A_CLASSIFYING_PROPERTY,
    }


# --------------------------------------------------------------------------------
# Where an address is normalized, and where one is admitted
# --------------------------------------------------------------------------------

# Every function of the package that admits a feed address: one that passes the column as a call
# keyword or assigns to it. Four are one path: the route builds the request, the service normalizes,
# the repository writes the row. The fifth reads a stored row back out. A sixth entry would be a
# second place an address is admitted, which is the premise the refusal's placement rests on.
#
# The bound: an attribute READ is not an admission and is not counted, so the fetch path's own
# `source.external_id` is deliberately absent. Six modules read the column that way, four of them
# reading a Google calendarId rather than a feed address.
ADDRESS_SITES: Final = frozenset(
    {
        "calendars.api.add_calendar_source",
        "calendars.repository.CalendarSourceRepository.create",
        "calendars.repository._as_record",
        "calendars.schemas.CalendarSourceResponse.of",
        "calendars.service.CalendarSourceService.add_source",
    }
)
NORMALIZING_SITES: Final = frozenset({"calendars.service.CalendarSourceService.add_source"})

EXTERNAL_ID = "external_id"
NORMALIZER = "normalize_feed_url"


def functions_by_reference(source: str, module: str) -> dict[str, set[str]]:
    """Every name this source calls, passes as a call keyword, or assigns to, by the using function.

    Qualified through the enclosing classes, so two methods of one name in two classes are two
    sites rather than one.

    Three shapes, and the bound is the shape that is absent: an attribute **read**. A module that
    reads a stored address does not admit one, and the Google adapter reads a provider's opaque
    identifier through the same attribute name, so counting reads would report four sites that
    handle no feed address at all.
    """
    found: dict[str, set[str]] = {}

    def walk(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                walk(child, f"{scope}.{child.name}")
                continue
            if isinstance(child, ast.Call):
                called = getattr(child.func, "id", None) or getattr(child.func, "attr", None)
                names = found.setdefault(scope, set())
                if called is not None:
                    names.add(called)
                names.update(keyword.arg for keyword in child.keywords if keyword.arg)
            if isinstance(child, ast.Attribute) and isinstance(child.ctx, ast.Store):
                found.setdefault(scope, set()).add(child.attr)
            walk(child, scope)

    walk(ast.parse(source), module)
    return found


def sites_referencing(source_root: Path, name: str) -> set[str]:
    """Every function of the package that calls ``name``, passes it as a keyword, or assigns it."""
    return {
        scope
        for path in sorted(source_root.rglob("*.py"))
        for scope, names in functions_by_reference(
            path.read_text(encoding="utf-8"), module_name(path, source_root)
        ).items()
        if name in names
    }


def test_the_walk_finds_a_reference_inside_a_method_of_a_class() -> None:
    # The positive control for the walk. A reference inside a method is the shape every site
    # below has, and a walk that lost the class would report a scope no assertion could match.
    found = functions_by_reference(
        "class Repository:\n    def create(self, value):\n        return row(external_id=value)\n",
        "here",
    )

    assert found["here.Repository.create"] == {"row", "external_id"}


def test_the_walk_finds_a_column_assigned_rather_than_passed() -> None:
    # The control for the second shape an admission has. A writer that assigns the column reaches
    # storage without passing it to anything, so a walk reading calls alone would not see it.
    found = functions_by_reference(
        "def admit(row, raw):\n    row.external_id = raw.strip()\n",
        "here",
    )

    assert "external_id" in found["here.admit"]


def test_a_feed_address_is_normalized_at_one_site(source_root: Path) -> None:
    # The premise of putting the refusal in the normalizer: there is one place a pasted address
    # becomes a stored one. A second caller is a second place to refuse from, and this goes red
    # rather than leaving that one unguarded.
    assert sites_referencing(source_root, NORMALIZER) == NORMALIZING_SITES


def test_every_site_that_admits_a_feed_address_is_accounted_for(source_root: Path) -> None:
    # Derived from the package, so a writer that passes the column or assigns it cannot appear
    # without a decision about whether it, too, admits an address the normalizer never saw. A
    # reader is outside the claim, and the docstring on the walk says which shape that is.
    assert sites_referencing(source_root, EXTERNAL_ID) == ADDRESS_SITES


def test_the_normalizing_site_is_on_the_writing_path(source_root: Path) -> None:
    # The two derivations crossed: the one site that normalizes is also a site that writes the
    # column. Were it not, an address would reach storage by a path the normalizer never saw.
    assert sites_referencing(source_root, EXTERNAL_ID) >= NORMALIZING_SITES
