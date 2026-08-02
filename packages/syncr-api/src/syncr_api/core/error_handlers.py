"""The HTTP mapping half of the error contract.

`errors.py` owns the vocabulary: the wire shape and the exception hierarchy a service
raises. This module owns what HTTP does with it: rendering a `Problem` as a response,
the four handlers, the map every app wires, and the response set the generated OpenAPI
document describes.

Split from `errors.py` because the two grow on different schedules. The vocabulary
gains a subclass per new domain error; the mapping gains a handler only when a new
exception category appears, which is rare.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Any

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import Response

from syncr_api.core.errors import (
    ERROR_BY_STATUS,
    GENERIC_HTTP_ERROR_TITLE,
    GENERIC_HTTP_ERROR_TYPE,
    PROBLEM_JSON_MEDIA_TYPE,
    FieldError,
    InternalError,
    Problem,
    SyncrError,
    ValidationFailed,
)
from syncr_common.logging import current_correlation_id, get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from starlette.requests import Request

# FastAPI keys handlers by exception type or by status code.
type ExceptionKey = type[Exception] | int
type ExceptionHandler = Callable[[Request, Exception], Response | Awaitable[Response]]

# This module is imported by both entrypoints, so the logger names the module rather
# than a process. A fault raised in the worker must not log `service: "syncr-api"`,
# which would be wrong exactly when someone is grepping by service to find it.
_log = get_logger("syncr.errors")


def _status_phrase(status: int) -> str:
    """The reason phrase for ``status``, or a generic title for a non-standard code.

    ``HTTPStatus(599)`` raises, and raising inside the error handler hands the request
    to the catch-all, which answers 500 and loses the status that was raised.
    """
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return GENERIC_HTTP_ERROR_TITLE


def _render(problem: Problem, *, headers: Mapping[str, str] | None = None) -> Response:
    return Response(
        content=problem.model_dump_json(exclude_none=True),
        status_code=problem.status,
        media_type=PROBLEM_JSON_MEDIA_TYPE,
        headers=dict(headers) if headers else None,
    )


def _field_path(location: tuple[int | str, ...]) -> str:
    """Flatten a Pydantic error location into a dotted field path (``body.title``)."""
    return ".".join(str(part) for part in location)


async def handle_syncr_error(_request: Request, exc: Exception) -> Response:
    """Map any :class:`SyncrError` subclass to problem details."""
    if not isinstance(exc, SyncrError):  # pragma: no cover - registered for SyncrError only
        raise exc
    return _render(exc.as_problem(), headers=exc.response_headers())


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
    client would have to parse two error formats. The framework's own headers are
    carried through, so a 401 keeps its ``WWW-Authenticate``.
    """
    if not isinstance(exc, HTTPException):  # pragma: no cover - registered for this type
        raise exc
    error_class = ERROR_BY_STATUS.get(exc.status_code)
    if error_class is not None:
        return await handle_syncr_error(request, error_class(str(exc.detail), headers=exc.headers))
    return _render(
        Problem(
            type=GENERIC_HTTP_ERROR_TYPE,
            title=_status_phrase(exc.status_code),
            status=exc.status_code,
            detail=str(exc.detail),
            instance=current_correlation_id(),
        ),
        headers=exc.headers,
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


# The error responses every route can answer, so the generated OpenAPI document
# describes the shape the api actually sends. Without this, FastAPI documents its own
# `HTTPValidationError` for 422 and nothing at all for 500, and the frontend would
# generate types for an error contract that never appears on the wire. A feature module
# adds the statuses it actually raises with `responses={**PROBLEM_RESPONSES, 409: ...}`.
#
# The document lists these under `application/json` because that is the media type
# FastAPI attaches to a `model`, while the wire carries `application/problem+json`.
# The schema is what codegen consumes, so it is the part that must be right here;
# pinning the documented media type belongs with the codegen slice that owns the
# committed document.
PROBLEM_RESPONSES: Mapping[int | str, dict[str, Any]] = {
    ValidationFailed.status: {"model": Problem, "description": ValidationFailed.title},
    InternalError.status: {"model": Problem, "description": InternalError.title},
}
