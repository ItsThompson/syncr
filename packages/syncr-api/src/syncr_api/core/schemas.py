"""The base every wire schema extends.

The frontend does not hand-write response types: it generates them from the OpenAPI
document this application emits, and TypeScript reads ``lastSeenAt`` rather than
``last_seen_at``. Fixing the casing in one base rather than per field means a new
schema cannot ship half-converted, which would be a contract that reads two ways.

``populate_by_name`` is on so a request body is accepted under either spelling. The
document advertises the camelCase alias, which is what a generated client sends; the
snake_case field name stays usable from a test and from the CLI without a second
schema.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class WireModel(BaseModel):
    """A request or response body, exposed to the wire in camelCase."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
