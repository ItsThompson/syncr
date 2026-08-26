"""One half-open span on the wire, spelled once.

``PeriodSpan`` and ``WireSpan`` described the same ``[start, end)`` pair of instants, so a
client generated from the document had two answers to whether ``end`` is inside it. The
collapse leaves one shape, and the sentence only the deleted class's docstring carried -- that
the span is present because it is what the denominator was derived from -- moved onto the
fields rather than being lost with it.

The claim is walked over the whole package rather than listed, because a fourth field typed
with a private copy of the span would reintroduce exactly the two-answers drift. The committed
document is crossed against the walk: it is what a caller can hold.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

from tests.test_alert_rules import repo_root
from tests.wire_census import models_extending_the_wire_base

if TYPE_CHECKING:
    from fastapi import FastAPI


# The shape every span on the wire takes, and the one whose name may describe a span in the
# document this directory commits.
SHARED_SPAN: Final = "WireSpan"

# The fields that carry a period's span to the wire today. Named so that narrowing any walk in
# this file is a red suite rather than a quieter one.
SPAN_FIELDS: Final = (
    ("syncr_api.budgets.schemas.BudgetResponse", "span"),
    ("syncr_api.reviews.schemas.BudgetReviewResponse", "span"),
    ("syncr_api.reviews.session_schemas.SessionRetroResponse", "span"),
    ("syncr_api.reviews.session_schemas.WeeklySessionResponse", "span"),
)

# The sentence the deleted class alone carried, which had to survive the collapse.
THE_DENOMINATOR_SENTENCE: Final = "it is what the denominator was derived from"

# The document the committed client was generated from.
CONTRACT: Final = repo_root() / "frontend" / "openapi.json"


def test_no_wire_shape_names_the_deleted_span() -> None:
    from syncr_api.core.schemas import WireSpan

    spans = [
        model
        for model in models_extending_the_wire_base()
        if issubclass(model, WireSpan) or model.__name__ == "PeriodSpan"
    ]

    assert [model.__name__ for model in spans] == ["WireSpan"], (
        f"{[model.__name__ for model in spans]}: a second wire shape for one half-open span "
        "gives a generated client two answers to whether end is inside it."
    )


def test_the_walk_reaches_every_field_named_here() -> None:
    # The control on the claims below: a walk resolved to none would pass forever.
    found = {
        f"{model.__module__}.{model.__qualname__}.{name}"
        for model in models_extending_the_wire_base()
        for name in model.model_fields
        if name == "span"
    }

    assert {f"{where}.{name}" for where, name in SPAN_FIELDS} <= found


def test_every_period_span_field_is_the_shared_type() -> None:
    by_where = {
        f"{model.__module__}.{model.__qualname__}": model
        for model in models_extending_the_wire_base()
    }

    for where, name in SPAN_FIELDS:
        field = by_where[where].model_fields[name]

        assert field.annotation is not None and field.annotation.__name__ == SHARED_SPAN, (
            f"{where}.{name} declares a span of its own. The one in core/schemas.py is the "
            "shape every span on this wire takes."
        )


def test_the_committed_contract_describes_a_half_open_span_once() -> None:
    document = json.loads(CONTRACT.read_text(encoding="utf-8"))
    schemas: dict[str, Any] = document["components"]["schemas"]

    assert "PeriodSpan" not in schemas, (
        f"{CONTRACT.name} still describes the deleted shape: regenerate with `just contract` "
        "and commit frontend/openapi.json together with frontend/src/api/schema.d.ts."
    )
    for where, _ in SPAN_FIELDS:
        name = where.rsplit(".", 1)[-1]
        span_property = schemas[name]["properties"]["span"]

        assert span_property.get("$ref") == f"#/components/schemas/{SHARED_SPAN}", (
            f"{name}.span does not reference the shared span: {span_property}"
        )
        assert THE_DENOMINATOR_SENTENCE in span_property["description"], (
            f"{name}.span lost the sentence saying why it is on the wire: the span is present "
            "because it is what the denominator was derived from."
        )


def test_the_live_document_agrees_with_the_committed_one(app: FastAPI) -> None:
    # The committed artifact can describe an older set of shapes than HEAD mounts, so the
    # sentence and the single spelling are asserted against the application's own document too:
    # a description dropped from a field redds here without waiting for a regeneration.
    live = app.openapi()["components"]["schemas"]

    assert "PeriodSpan" not in live
    for where, _ in SPAN_FIELDS:
        name = where.rsplit(".", 1)[-1]
        span_property = live[name]["properties"]["span"]

        assert span_property.get("$ref") == f"#/components/schemas/{SHARED_SPAN}", (
            f"{name}.span does not reference the shared span: {span_property}"
        )
        assert THE_DENOMINATOR_SENTENCE in span_property["description"]
