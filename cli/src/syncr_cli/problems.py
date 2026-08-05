"""RFC 9457 problem details, as the CLI reads them and as the CLI mints its own.

One error shape whatever the source. The api answers problem details on every route, and a
failure that never reached the api (a bad flag, an unreachable host, a wait that ran out) is
carried in the same five members under a ``syncr:cli-`` type, so an agent writes one parser
for the ``problem`` member of :class:`~syncr_cli.results.CliResult` rather than one per
origin.

**Reading is deliberately tolerant.** A 502 from a proxy that never reached the application
answers HTML, and a caller pointed at the wrong port gets whatever that port serves. Neither
is a reason to fault: the status is what the exit code falls back to, and the body is
reported as the detail it turned out to be.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Final

from syncr_cli.exit_codes import ExitCode

# The types the CLI mints for failures of its own. Namespaced the way the api's are, so the
# `type` member is one vocabulary and a caller matching on a prefix sees where it came from.
CLI_USAGE: Final = "syncr:cli-usage"
CLI_NOT_AUTHENTICATED: Final = "syncr:cli-not-authenticated"
CLI_API_UNREACHABLE: Final = "syncr:cli-api-unreachable"
CLI_TIMED_OUT: Final = "syncr:cli-timed-out"
CLI_FAILURE: Final = "syncr:cli-failure"
CLI_MALFORMED_RESPONSE: Final = "syncr:cli-malformed-response"

# What the api's problem types mean to a process that has to exit with a number. The api's own
# vocabulary is not importable here -- the CLI ships nothing server-side -- so an unlisted type
# falls back to `exit_code_for_status`, which is what keeps a type this table has never seen
# from becoming a generic failure by accident.
EXIT_CODE_BY_PROBLEM_TYPE: Final[dict[str, ExitCode]] = {
    "syncr:malformed-request": ExitCode.USAGE,
    "syncr:unauthorized": ExitCode.NOT_AUTHENTICATED,
    "syncr:forbidden": ExitCode.INSUFFICIENT_SCOPE,
    "syncr:origin-rejected": ExitCode.FAILURE,
    "syncr:not-found": ExitCode.NOT_FOUND,
    "syncr:conflict": ExitCode.CONFLICT,
    "syncr:idempotency-request-in-flight": ExitCode.CONFLICT,
    "syncr:validation-failed": ExitCode.VALIDATION_FAILED,
    # A rate limit and a dependency outage are both "the API will not serve this now", which is
    # what code 11 says. Neither is the caller's mistake, so neither is a usage error, and
    # answering 1 would tell an agent to stop rather than to wait.
    "syncr:rate-limited": ExitCode.API_UNAVAILABLE,
    "syncr:dependency-unavailable": ExitCode.API_UNAVAILABLE,
    "syncr:internal-error": ExitCode.FAILURE,
    # `syncr:http-error` is deliberately absent. It is the type the api gives a status with no
    # domain error of its own, and the type this module gives a body that was not problem details
    # at all, so a row for it would decide the code from a name that carries no information and
    # would answer 1 for the 502 a proxy sends. It falls through to the status, which is the only
    # thing such a response actually said.
    # The Authorization Server's five. An invalid grant is a dead refresh token, which is the
    # condition code 3 exists for; an unknown client is a deployment this build cannot
    # authenticate against, which no re-login fixes, so it is a plain failure.
    "syncr:oauth-invalid-request": ExitCode.USAGE,
    "syncr:oauth-invalid-grant": ExitCode.NOT_AUTHENTICATED,
    "syncr:oauth-invalid-token": ExitCode.NOT_AUTHENTICATED,
    "syncr:oauth-invalid-client": ExitCode.FAILURE,
    "syncr:oauth-unsupported-grant-type": ExitCode.FAILURE,
    CLI_USAGE: ExitCode.USAGE,
    CLI_NOT_AUTHENTICATED: ExitCode.NOT_AUTHENTICATED,
    CLI_API_UNREACHABLE: ExitCode.API_UNAVAILABLE,
    CLI_TIMED_OUT: ExitCode.TIMED_OUT,
    CLI_FAILURE: ExitCode.FAILURE,
    CLI_MALFORMED_RESPONSE: ExitCode.FAILURE,
}

# The status a problem carries when it never had one: a transport failure, a bad flag, a wait
# that ran out. Zero rather than a 4xx, because no HTTP exchange produced it.
NO_STATUS: Final = 0

_EXIT_CODE_BY_STATUS: Final[dict[int, ExitCode]] = {
    400: ExitCode.USAGE,
    401: ExitCode.NOT_AUTHENTICATED,
    403: ExitCode.INSUFFICIENT_SCOPE,
    404: ExitCode.NOT_FOUND,
    409: ExitCode.CONFLICT,
    422: ExitCode.VALIDATION_FAILED,
    429: ExitCode.API_UNAVAILABLE,
    502: ExitCode.API_UNAVAILABLE,
    503: ExitCode.API_UNAVAILABLE,
    504: ExitCode.API_UNAVAILABLE,
}


@dataclass(frozen=True, slots=True)
class FieldProblem:
    """One field-level validation failure, as a 422 lists them."""

    field: str
    message: str


@dataclass(frozen=True, slots=True)
class Problem:
    """Why a command failed, in the five members every caller reads."""

    type: str
    title: str
    status: int
    detail: str
    instance: str | None = None
    errors: tuple[FieldProblem, ...] = field(default_factory=tuple)

    @property
    def exit_code(self) -> ExitCode:
        """The number this problem exits with.

        By type where the type is known, and by status otherwise. A type this build has never
        seen is the expected case rather than an exceptional one: the api may name a condition
        that postdates this binary, and a 404 is a 404 whatever it calls itself.
        """
        known = EXIT_CODE_BY_PROBLEM_TYPE.get(self.type)
        if known is not None:
            return known
        return exit_code_for_status(self.status)


def exit_code_for_status(status: int) -> ExitCode:
    """The code an HTTP status alone justifies.

    Every 5xx that is not one of the three gateway statuses is a generic failure: the request
    reached the application and the application faulted, which is a different instruction to a
    caller than "come back later".
    """
    return _EXIT_CODE_BY_STATUS.get(status, ExitCode.FAILURE)


def cli_problem(problem_type: str, title: str, detail: str) -> Problem:
    """A problem the CLI itself is reporting, so no HTTP status is claimed."""
    return Problem(type=problem_type, title=title, status=NO_STATUS, detail=detail)


def read_problem(status: int, body: bytes) -> Problem:
    """The problem a response carries, or the best account of a body that is not one."""
    payload = _decode(body)
    if payload is None:
        return Problem(
            type="syncr:http-error",
            title=f"HTTP {status}",
            status=status,
            detail=_readable(body),
        )
    return Problem(
        type=_text(payload, "type") or "syncr:http-error",
        title=_text(payload, "title") or f"HTTP {status}",
        status=_status(payload, status),
        detail=_text(payload, "detail") or _readable(body),
        instance=_text(payload, "instance") or None,
        errors=_field_problems(payload.get("errors")),
    )


def _decode(body: bytes) -> dict[str, Any] | None:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) else ""


def _status(payload: dict[str, Any], fallback: int) -> int:
    value = payload.get("status")
    return value if isinstance(value, int) and not isinstance(value, bool) else fallback


def _field_problems(raw: Any) -> tuple[FieldProblem, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(
        FieldProblem(field=_text(entry, "field"), message=_text(entry, "message"))
        for entry in raw
        if isinstance(entry, dict)
    )


# How much of a body that is not problem details is worth repeating. Long enough to recognize
# a proxy's error page, short enough that it does not become the output.
_DETAIL_LIMIT: Final = 200


def _readable(body: bytes) -> str:
    text = " ".join(body.decode("utf-8", errors="replace").split())
    if not text:
        return "The API answered with an empty body."
    if len(text) <= _DETAIL_LIMIT:
        return text
    return f"{text[:_DETAIL_LIMIT]}..."
