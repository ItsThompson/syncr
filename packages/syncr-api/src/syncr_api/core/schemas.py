"""The base every wire schema extends.

The frontend does not hand-write response types: it generates them from the OpenAPI
document this application emits, and TypeScript reads ``lastSeenAt`` rather than
``last_seen_at``. Fixing the casing in one base rather than per field means a new
schema cannot ship half-converted, which would be a contract that reads two ways.

``populate_by_name`` is on so a request body is accepted under either spelling. The
document advertises the camelCase alias, which is what a generated client sends; the
snake_case field name stays usable from a test and from the CLI without a second
schema.

``WireDecimal`` is here for the same reason the casing is: a shape that reads two ways is a
contract that drifts. Pydantic renders a bare ``Decimal`` as ``anyOf: [number, string]`` and
serializes it as a string, so the generated TypeScript would be ``number | string`` and every
caller would have to narrow it before doing arithmetic. Both readings are pinned to a number
here, and exact ``Decimal`` arithmetic stays on the server where the budget is computed.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer, WithJsonSchema
from pydantic.alias_generators import to_camel

# A fractional value the wire carries as a number. Field-level bounds still apply: only the
# type and the serialized form are fixed here.
type WireDecimal = Annotated[
    Decimal,
    PlainSerializer(float, return_type=float, when_used="json"),
    WithJsonSchema({"type": "number"}),
]


class WireModel(BaseModel):
    """A request or response body, exposed to the wire in camelCase."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
