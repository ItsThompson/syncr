"""The public wire shape for a stored pin."""

from __future__ import annotations

import json
from pathlib import Path

from syncr_api.pins.schemas import PinResponse

CONTRACT = Path(__file__).resolve().parents[3] / "frontend" / "openapi.json"
OBJECTIVE_DELTA = {
    "description": "What the user's choice cost in objective units, under weightSetVersion. "
    "Positive when the user's placement is worse under those weights, and zero for a pin that "
    "keeps a block where it already is.",
    "title": "Objectivedelta",
    "type": "number",
}


def test_pin_response_requires_a_numeric_objective_delta() -> None:
    schema = PinResponse.model_json_schema(by_alias=True)

    assert "objectiveDelta" in schema["required"]
    assert schema["properties"]["objectiveDelta"] == OBJECTIVE_DELTA


def test_committed_contract_requires_a_numeric_pin_objective_delta() -> None:
    document = json.loads(CONTRACT.read_text(encoding="utf-8"))
    schema = document["components"]["schemas"]["PinResponse"]

    assert "objectiveDelta" in schema["required"]
    assert schema["properties"]["objectiveDelta"] == OBJECTIVE_DELTA
