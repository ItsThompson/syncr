"""The error vocabulary: the wire shape and the hierarchy a service raises.

The service layer raises :class:`SyncrError` subclasses. What HTTP does with them, the
four handlers and the response set the generated document describes, lives in
``error_handlers.py``: the two grow on different schedules, since this file gains a
subclass per new domain error while the mapping rarely changes at all.

One shape for every caller, so the browser, the CLI, and an AI agent all read the same
error. ``instance`` carries the correlation id, not the request path: the id is what
turns a reported error into a log query.

A ``detail`` that says only what broke fails review. Where a capability degraded,
it names the capabilities that survive.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, Field

from syncr_common.health import RETRY_AFTER_SECONDS
from syncr_common.logging import current_correlation_id

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

PROBLEM_JSON_MEDIA_TYPE = "application/problem+json"


class FieldError(BaseModel):
    """One field-level validation failure. Present on 422 responses only."""

    field: str
    message: str


def _publish_the_declared_types(field_schema: dict[str, Any]) -> None:
    """Give the ``type`` field its vocabulary when the schema is generated.

    Deferred to generation time because the walk cannot run where the field is declared: the
    classes that declare a type are all below it, and some are in modules this one does not
    import. Pydantic calls this while building the JSON schema, by which point the
    application has imported every one of them.
    """
    field_schema["enum"] = declared_problem_types()


class Problem(BaseModel):
    """RFC 9457 problem details. Optional members are omitted from the wire."""

    # A string rather than an enum, because one type a caller can receive is declared by no
    # class: the handler for a status no subclass claims renders GENERIC_HTTP_ERROR_TYPE. So
    # the vocabulary is published in the schema rather than enforced here.
    type: str = Field(json_schema_extra=_publish_the_declared_types)
    title: str
    status: int
    detail: str
    instance: str | None = None
    errors: list[FieldError] | None = None


class SyncrError(Exception):
    """Base of the service-layer error hierarchy mapped to problem details.

    A subclass fixes the wire ``type``, the HTTP ``status``, and the short stable
    ``title``. The caller supplies ``detail``, and a validation failure attaches
    field-level ``errors``.
    """

    type: ClassVar[str]
    status: ClassVar[int]
    title: ClassVar[str]
    # Seconds a 503 or 429 asks the caller to wait. None means no `Retry-After`.
    retry_after_seconds: ClassVar[int | None] = None

    def __init__(
        self,
        detail: str,
        *,
        errors: Sequence[FieldError] | None = None,
        instance: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.detail = detail
        self.errors = list(errors) if errors else None
        self.instance = instance
        # Response headers this error needs beyond `Retry-After`. Section 13 requires
        # none, but an OAuth 401 needs `WWW-Authenticate`, so the seam exists here
        # rather than having the slice that needs it edit the error contract.
        self.headers = dict(headers) if headers else {}
        super().__init__(detail)

    def response_headers(self) -> dict[str, str]:
        """Every header this error's response carries."""
        headers = dict(self.headers)
        if self.retry_after_seconds:
            headers["Retry-After"] = str(self.retry_after_seconds)
        return headers

    def as_problem(self) -> Problem:
        """Render this error as its wire shape."""
        return Problem(
            type=self.type,
            title=self.title,
            status=self.status,
            detail=self.detail,
            instance=self.instance or current_correlation_id(),
            errors=self.errors,
        )


class MalformedRequest(SyncrError):
    type = "syncr:malformed-request"
    status = 400
    title = "Malformed request"


class Unauthorized(SyncrError):
    type = "syncr:unauthorized"
    status = 401
    title = "Authentication required"


class Forbidden(SyncrError):
    """403: a valid credential with insufficient scope.

    Not raised for a resource owned by another tenant; that is a 404, so a caller
    never learns the resource exists.
    """

    type = "syncr:forbidden"
    status = 403
    title = "Insufficient scope"


class OriginRejected(SyncrError):
    """403: an unsafe request from an origin this deployment does not serve.

    Its own type rather than :class:`Forbidden`, because the caller's credential and
    scope are not what was wrong: the request was rejected before either was
    considered, and a title of "insufficient scope" would send someone looking for a
    permission problem that does not exist.
    """

    type = "syncr:origin-rejected"
    status = 403
    title = "Cross-origin request rejected"


class NotFound(SyncrError):
    type = "syncr:not-found"
    status = 404
    title = "Resource not found"


class Conflict(SyncrError):
    type = "syncr:conflict"
    status = 409
    title = "Conflict with the current state"


class ValidationFailed(SyncrError):
    type = "syncr:validation-failed"
    status = 422
    title = "Validation failed"


class RateLimited(SyncrError):
    type = "syncr:rate-limited"
    status = 429
    title = "Rate limited"
    retry_after_seconds = 1


class DependencyUnavailable(SyncrError):
    type = "syncr:dependency-unavailable"
    status = 503
    title = "Dependency unavailable"
    # The same wait a not-ready readiness answer asks for, derived rather than
    # restated, because both mean "come back when the dependency is up".
    retry_after_seconds = RETRY_AFTER_SECONDS


class InternalError(SyncrError):
    type = "syncr:internal-error"
    status = 500
    title = "Internal server error"


# The domain error each framework-raised status maps onto, so a routing 404 and a
# service-raised 404 are the same shape on the wire. A status with no entry (405,
# say) still renders as problem details, under a generic type.
ERROR_BY_STATUS: dict[int, type[SyncrError]] = {
    error.status: error
    for error in (
        MalformedRequest,
        Unauthorized,
        Forbidden,
        NotFound,
        Conflict,
        ValidationFailed,
        RateLimited,
        DependencyUnavailable,
    )
}

GENERIC_HTTP_ERROR_TYPE = "syncr:http-error"
GENERIC_HTTP_ERROR_TITLE = "HTTP error"


def _descendants(root: type[SyncrError]) -> Iterator[type[SyncrError]]:
    """Every subclass of ``root``, at any depth."""
    for subclass in root.__subclasses__():
        yield subclass
        yield from _descendants(subclass)


def declared_problem_types() -> list[str]:
    """Every wire ``type`` the error hierarchy declares, sorted.

    Walked rather than listed, so a new subclass reaches the published contract by existing.
    A subclass that declares none sends its parent's, which is already a member.
    """
    return sorted(
        {subclass.type for subclass in _descendants(SyncrError) if "type" in vars(subclass)}
    )
