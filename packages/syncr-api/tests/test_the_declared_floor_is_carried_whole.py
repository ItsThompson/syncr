"""The declared Area floor reaches ``AreaBudget`` as the Area states it, netted by nothing.

The producer reads ``share.floor_minutes`` twice to net it into the solver's floor and the probe's
reservation, and a third quantity that names user intent is carried only if every construction
site states it straight from the Area row. A subtraction or a clamp at any site would silently
turn the declaration into one more netted figure.

Two readings guard that. One walks the source: every ``AreaBudget`` construction in the api and in
the assembler fakes is parsed, and each has to state the field without netting anything into it.
The other runs the producer over an Area whose immovable placements have already lowered both
netted floors, and holds the declared figure above them.
"""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from syncr_api.plans.netting import PlacedTime, Placement
from syncr_api.plans.reservations import area_budgets
from syncr_domain.identity import BindingRef
from tests.assembly_fakes import MINUTES_PER_HOUR, NOW, an_area, between

# The construction sites the boundary walk covers: the api package, and the assembler fakes beside
# it. The walk is over files, so a new site anywhere under either path is walked without this
# module learning its address.
_API_SRC = Path(__file__).resolve().parents[1] / "src" / "syncr_api"
_ASSEMBLY_FAKES = Path(__file__).resolve().parent / "assembly_fakes.py"


def _area_budget_constructions(tree: ast.AST) -> list[ast.Call]:
    """Every call that constructs an ``AreaBudget``, however it was imported."""
    found: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        named = isinstance(function, ast.Name) and function.id == "AreaBudget"
        member = isinstance(function, ast.Attribute) and function.attr == "AreaBudget"
        if named or member:
            found.append(node)
    return found


def _is_netted(value: ast.expr) -> bool:
    """Whether the stated figure subtracts a placement set or clamps, instead of naming one.

    Structural only: netting hidden inside a helper function reads as a plain call and passes
    here. That is acceptable while the producer is pinned verbatim to ``share.floor_minutes``;
    a second producer would need its own behavioral run, not just this walk.
    """
    for node in ast.walk(value):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub):
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "max":
            return True
    return False


def _stated_sources() -> tuple[list[tuple[Path, ast.Call]], list[str]]:
    # Parsed at collection time. The tree is a few hundred small modules, so the walk costs
    # single-digit milliseconds; revisit only if collection time ever matters.
    sources = [*_API_SRC.rglob("*.py"), _ASSEMBLY_FAKES]
    stated: list[tuple[Path, ast.Call]] = []
    ids: list[str] = []
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found = _area_budget_constructions(tree)
        stated.extend((path, node) for node in found)
        ids.extend(f"{path.name}:{node.lineno}" for node in found)
    return stated, ids


_STATED_SOURCES, _STATED_IDS = _stated_sources()


@pytest.mark.parametrize(("path", "construction"), _STATED_SOURCES, ids=_STATED_IDS)
def test_every_area_budget_construction_states_the_declared_floor_unnetted(
    path: Path, construction: ast.Call
) -> None:
    declared = [
        keyword.value
        for keyword in construction.keywords
        if keyword.arg == "declared_floor_minutes"
    ]
    assert len(declared) == 1, f"{path}:{construction.lineno} states no declared floor"
    assert not _is_netted(declared[0]), (
        f"{path}:{construction.lineno} nets the declared floor instead of carrying it whole"
    )


def test_the_producer_reads_the_declaration_off_the_share_itself() -> None:
    source = (_API_SRC / "plans" / "reservations.py").read_text(encoding="utf-8")
    tree = ast.parse(source, filename="reservations.py")
    producers = [
        node
        for node in _area_budget_constructions(tree)
        if any(keyword.arg == "declared_floor_minutes" for keyword in node.keywords)
    ]
    assert len(producers) == 1
    (keyword,) = [k for k in producers[0].keywords if k.arg == "declared_floor_minutes"]
    assert ast.unparse(keyword.value) == "share.floor_minutes", (
        "the declared floor must be read from the Area row, not derived from a netting"
    )


def test_the_declared_floor_survives_the_netting_applied_to_its_pair() -> None:
    area = an_area(floor_hours=Decimal(5))
    placed = PlacedTime(
        (
            # An immovable hour and a half, wholly lived: both netted floors give it back, and a
            # declared floor netted the same way would fall with them.
            Placement(
                binding=BindingRef.for_task(uuid4()),
                interval=between(8, 9.5, day=1),
                area_id=area.id,
                immovable=True,
                attributed=between(8, 9.5, day=1),
            ),
        ),
        now=NOW,
    )

    (budget,) = area_budgets([area], discretionary_minutes=2400, placed=placed, caps={})

    assert budget.declared_floor_minutes == 5 * MINUTES_PER_HOUR
    assert budget.floor_minutes == 3 * MINUTES_PER_HOUR + 30
    assert budget.floor_reservation_minutes == 3 * MINUTES_PER_HOUR + 30
