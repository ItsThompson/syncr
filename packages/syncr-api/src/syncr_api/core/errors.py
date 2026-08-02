"""The error contract: the single boundary between the service layer and HTTP.

The service layer raises :class:`SyncrError` subclasses; one handler maps the whole
hierarchy to RFC 9457 ``application/problem+json``, so the browser, the CLI, and an
AI agent all read one error shape. FastAPI's own ``RequestValidationError`` is
mapped into the same shape, and an unhandled exception renders as a generic 500
rather than leaking a stack trace.

``instance`` carries the correlation id, not the request path: the id is what turns
a reported error into a log query.

A ``detail`` that says only what broke fails review. Where a capability degraded,
it names the capabilities that survive.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar

from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from starlette.exceptions import HTTPException
from starlette.responses import Response

from syncr_common.logging import current_correlation_id, get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from starlette.requests import Request

PROBLEM_JSON_MEDIA_TYPE = "application/problem+json"

# FastAPI keys handlers by exception type or by status code.
type ExceptionKey = type[Exception] | int
type ExceptionHandler = Callable[[Request, Exception], Response | Awaitable[Response]]

_log = get_logger("syncr-api")


class FieldError(BaseModel):
    """One field-level validation failure. Present on 422 responses only."""

    field: str
    message: str


class Problem(BaseModel):
    """RFC 9457 problem details. Optional members are omitted from the wire."""

    type: str
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
    ) -> None:
        self.detail = detail
        self.errors = list(errors) if errors else None
        self.instance = instance
        super().__init__(detail)

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
    retry_after_seconds = 5


class InternalError(SyncrError):
    type = "syncr:internal-error"
    status = 500
    title = "Internal server error"


# The domain error each framework-raised status maps onto, so a routing 404 and a
# service-raised 404 are the same shape on the wire. A status with no entry (405,
# say) still renders as problem details, under a generic type.
_ERROR_BY_STATUS: dict[int, type[SyncrError]] = {
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


def _render(problem: Problem, *, retry_after_seconds: int | None = None) -> Response:
    headers = {"Retry-After": str(retry_after_seconds)} if retry_after_seconds else None
    return Response(
        content=problem.model_dump_json(exclude_none=True),
        status_code=problem.status,
        media_type=PROBLEM_JSON_MEDIA_TYPE,
        headers=headers,
    )


def _field_path(location: tuple[int | str, ...]) -> str:
    """Flatten a Pydantic error location into a dotted field path (``body.title``)."""
    return ".".join(str(part) for part in location)


async def handle_syncr_error(_request: Request, exc: Exception) -> Response:
    """Map any :class:`SyncrError` subclass to problem details."""
    if not isinstance(exc, SyncrError):  # pragma: no cover - registered for SyncrError only
        raise exc
    return _render(exc.as_problem(), retry_after_seconds=exc.retry_after_seconds)


async def handle_request_validation_error(_request: Request, exc: Exception) -> Response:
    """Map FastAPI's request-validation failure into the same problem shape."""
    if not isinstance(exc, RequestValidationError):  # pragma: no cover - registered for this type
        raise exc
    errors = [
        FieldError(field=_field_path(error["loc"]), message=str(error["msg"]))
        for error in exc.errors()
    ]
    return _render(
        ValidationFailed(
            f"{len(errors)} request field(s) failed validation. Nothing was changed.",
            errors=errors,
        ).as_problem()
    )


async def handle_http_exception(request: Request, exc: Exception) -> Response:
    """Map a framework-raised ``HTTPException`` into the same problem shape.

    Without this, an unrouted path and a wrong method answer in Starlette's own
    ``{"detail": ...}`` shape while every other error answers problem details, so a
    client would have to parse two error formats.
    """
    if not isinstance(exc, HTTPException):  # pragma: no cover - registered for this type
        raise exc
    error_class = _ERROR_BY_STATUS.get(exc.status_code)
    if error_class is not None:
        return await handle_syncr_error(request, error_class(str(exc.detail)))
    return _render(
        Problem(
            type=GENERIC_HTTP_ERROR_TYPE,
            title=HTTPStatus(exc.status_code).phrase,
            status=exc.status_code,
            detail=str(exc.detail),
            instance=current_correlation_id(),
        )
    )


async def handle_unexpected(request: Request, exc: Exception) -> Response:
    """Render an unhandled exception as a generic 500.

    The single structured-fault log site: one ``api.request.failed`` line carrying
    the exception and the route. The response body stays generic so no stack trace
    or original message reaches the client.
    """
    _log.error("api.request.failed", exc_info=exc, route=request.url.path)
    return _render(
        InternalError("An unexpected error occurred. The request was not applied.").as_problem()
    )


def build_exception_handlers() -> Mapping[ExceptionKey, ExceptionHandler]:
    """The handler map every app wires, so no route can forget to map its errors.

    One handler for the whole :class:`SyncrError` hierarchy (Starlette dispatches by
    MRO), one for the framework's own ``HTTPException`` and request-validation
    failure, and a catch-all so an unhandled fault renders as problem details
    instead of leaking. The keys are MRO-disjoint, so registration order is
    irrelevant.
    """
    return {
        SyncrError: handle_syncr_error,
        HTTPException: handle_http_exception,
        RequestValidationError: handle_request_validation_error,
        Exception: handle_unexpected,
    }
