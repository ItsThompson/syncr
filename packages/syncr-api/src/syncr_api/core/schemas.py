"""The base every wire schema extends.

The frontend does not hand-write response types: it generates them from the OpenAPI
document this application emits, and TypeScript reads ``lastSeenAt`` rather than
``last_seen_at``. Fixing the casing in one base rather than per field means a new
schema cannot ship half-converted, which would be a contract that reads two ways.

**The rule scopes to a request or response body.** A path parameter is snake_cased --
``iso_week``, ``source_id``, ``anchor_type_id`` -- and a multi-word query parameter this api
names itself is camelCased -- ``areaId``, ``atRisk``. So a new route spells its path parameter
in snake_case, which is the surface this base does not reach. The other body surface it does not
reach is the OAuth endpoints' form-encoded requests, whose member names RFC 6749 section 4.1.3
fixes as ``grant_type`` and the rest.

``populate_by_name`` is on so a request body is accepted under either spelling. The
document advertises the camelCase alias, which is what a generated client sends; the
snake_case field name stays usable from a test and from the CLI without a second
schema.

``WireDecimal`` is here for the same reason the casing is: a shape that reads two ways is a
contract that drifts. Pydantic renders a bare ``Decimal`` as ``anyOf: [number, string]`` and
serializes it as a string, so the generated TypeScript would be ``number | string`` and every
caller would have to narrow it before doing arithmetic. Both readings are pinned to a number
here, and exact ``Decimal`` arithmetic stays on the server where the budget is computed.

``WireSpan`` is here because a span is the shape most of the plan crosses the wire in: a week,
a block, a rejected candidate window, a forbidden window, an unfilled slot. Every one of them is
the same half-open pair of instants, and a shape declared per feature is a shape whose halves
come to be read two ways.

``WireInstant`` is here because a datetime with no offset names no instant. A bare ``datetime``
reads ``"2026-03-08T09:00"`` and ``"2026-03-08"`` as wall time in whatever zone the process runs
in, so a caller a zone away from the server stores a deadline hours or a day from the one it
sent, and is told nothing. This type refuses both readings and renders the offset back, which is
what ``format: date-time`` already promises a caller: RFC 3339 section 5.6 has no offset-less
form.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    WithJsonSchema,
)
from pydantic.alias_generators import to_camel

if TYPE_CHECKING:
    from syncr_domain.intervals import Interval

# A fractional value the wire carries as a number. Field-level bounds still apply: only the
# type and the serialized form are fixed here.
type WireDecimal = Annotated[
    Decimal,
    PlainSerializer(float, return_type=float, when_used="json"),
    WithJsonSchema({"type": "number"}),
]

# Every instant the api accepts or returns, in either direction. An aware value is the only one
# this admits, and pydantic renders an aware value with its offset, so a response cannot omit
# one.
type WireInstant = AwareDatetime


class WireModel(BaseModel):
    """A request or response body, exposed to the wire in camelCase."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class WireSpan(WireModel):
    """A half-open interval, ``[start, end)``, as every span on the wire is spelled.

    Half-open in both directions of reading: a span ending at 09:00 does not include 09:00, and
    another may begin exactly there. The length is not carried, because two instants already
    state it and a third field could disagree with them: a span across a daylight-saving
    transition is 23 or 25 hours long and a reader that needs the figure takes the difference.
    """

    start: WireInstant = Field(description="When the span begins. Inside it.")
    end: WireInstant = Field(description="When the span ends. NOT inside it.")

    @classmethod
    def of(cls, interval: Interval) -> Self:
        """The wire shape of one resolved interval."""
        return cls(start=interval.start, end=interval.end)
