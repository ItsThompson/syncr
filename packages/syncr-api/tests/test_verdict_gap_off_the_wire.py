"""The verdict event's gap column never reaches the wire, in either of its two spellings.

``verdict_events.largest_gap_minutes`` feeds a product metric computed by a job that reads the
table directly; no route, event, or panel ever carries it, and the committed OpenAPI document is
generated from routes alone. A future reader could still add it to a wire shape believing a panel
needs the figure, which is the drift this file exists to redden: both sources of the census are
walked, so a field written before its route mounts is caught too.

The old name is asserted beside the new one, because a shape that still carried the pre-rename
spelling would be carrying a column the database no longer has.

Every claim is taken over the application's own document as well, since a committed artifact can
describe an older set of routes than HEAD mounts.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

from tests.test_alert_rules import repo_root
from tests.wire_census import models_extending_the_wire_base

if TYPE_CHECKING:
    from collections.abc import Iterator


# Both spellings of the column, camel-cased as the wire spells body members.
FORBIDDEN_FIELDS: Final = frozenset({"shortfallMinutes", "largestGapMinutes"})

# The document the committed client was generated from. The same artifact
# ``test_wire_casing_scope.py`` reads, for the same reason: it is what a caller can hold.
CONTRACT: Final = repo_root() / "frontend" / "openapi.json"


def properties_of(document: dict[str, Any]) -> Iterator[str]:
    """Every property name declared anywhere in an OpenAPI document."""
    schemas = document.get("components", {}).get("schemas", {})
    for schema in schemas.values():
        yield from schema.get("properties", {})


def field_names_of_wire_models() -> set[str]:
    """Every member name of every shape the api package declares over the wire base."""
    return {name for model in models_extending_the_wire_base() for name in model.model_fields}


def test_no_wire_shape_carries_the_gap_column() -> None:
    found = field_names_of_wire_models() & FORBIDDEN_FIELDS

    assert found == set(), (
        f"{found}. The verdict event's gap figure feeds a metric job that reads the table, not any "
        "panel: a shape carrying it puts a column with no aggregate on the wire."
    )


def test_the_walk_reads_shapes_rather_than_passing_on_an_empty_population() -> None:
    # The control on the walk above: a rule stated over every wire shape that resolved to none
    # would pass forever.
    names = field_names_of_wire_models()

    assert len(names) >= 100, f"{len(names)} members found: the walk has gone blind"


def test_the_committed_contract_declares_neither_spelling() -> None:
    document = json.loads(CONTRACT.read_text(encoding="utf-8"))
    found = set(properties_of(document)) & FORBIDDEN_FIELDS

    assert found == set(), (
        f"{found} appears in {CONTRACT.name}: the contract was regenerated over a shape this "
        "directory refuses, or carries a spelling of the column the database no longer has."
    )
