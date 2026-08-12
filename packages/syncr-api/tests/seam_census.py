"""Which class each seam of a composed service is wired to, read out of the tree as text.

Two seams of the week assembler are protocols, so what a compositor binds them to is invisible to
every type check and to every unit assembly that passes its own double. The reading that answers
"what does production wire here" is therefore a reading of the source, and it is one function rather
than one per seam: the placement seam and the habit outcome seam went stale in the same way, and a
second walk of the same shape is how two guards come to cover different spellings of one claim.

**The composition is read from the source, not imported.** What is under test is which class the
keyword is bound to at each place the service is composed, and the module that composes it also has
to have imported that class from the module that defines it: a local class of the same name
satisfies
a name check while reading nothing, which is the shape a stub takes.

**Every name a source can reach the composed service by is resolved.** The bare name, the
module-qualified attribute, and any local name an ``import from`` binds it to, through
``source_census.imported_as``, which is this member's canonical alias reader. What still escapes: a
service bound by assignment (``Composer = WeekAssembler`` and then ``Composer(...)``), and a keyword
bound to anything but a direct call, such as an already-built reader or a helper's return. A reader
under another name does not hide, because what is returned is the name the keyword binds and a
caller
asserting an exact name fails loudly on any other.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, NamedTuple

from tests.source_census import imported_as, named

if TYPE_CHECKING:
    from pathlib import Path


class Wiring(NamedTuple):
    """One composition: where it is, what the seam reads, and where that class was imported from."""

    module: str
    reader: str
    imported_from: str | None


def seam_wirings(source_root: Path, *, composed: type, keyword: str) -> list[Wiring]:
    """Every composition of ``composed`` under ``source_root``, with the class ``keyword`` binds.

    Returns data rather than asserting, so a census, its controls and any crossing over it all drive
    one walk.
    """
    found: list[Wiring] = []
    for module in sorted(source_root.rglob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        relative = str(module.relative_to(source_root))
        composing = frozenset({composed.__name__}) | imported_as(
            tree, module=composed.__module__, names=(composed.__name__,)
        )
        found.extend(
            Wiring(relative, reader, imported_from(tree, reader))
            for node in ast.walk(tree)
            if (reader := _seam_of(node, composing, keyword)) is not None
        )
    return found


def imported_from(tree: ast.Module, name: str) -> str | None:
    """The module a source imported ``name`` from, or nothing when it defines or shadows it."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(
            (alias.asname or alias.name) == name for alias in node.names
        ):
            return node.module
    return None


def _seam_of(node: ast.AST, composing: frozenset[str], keyword: str) -> str | None:
    """The class this node's seam is constructed from, if it composes one of ``composing``.

    ``composing`` holds every local name the source can reach the composed service by, so a
    module-qualified call and an ``as`` alias are read as compositions rather than passed over. A
    keyword bound to anything but a call has no class to name.
    """
    if not isinstance(node, ast.Call) or named(node.func) not in composing:
        return None
    bound = {one.arg: one.value for one in node.keywords}
    seam = bound.get(keyword)
    if not isinstance(seam, ast.Call):
        return None
    return named(seam.func)
