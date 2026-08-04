"""Structured logging: JSON lines, one event per line, redacted by key name.

Every line is JSON in every environment, so a log consumer never has to detect a
format. Two rules are enforced here rather than left to call sites:

Redaction. A line carrying ``Kontron Placement Interview`` discloses a job search
to anyone with log access, and a line carrying an anchor location discloses where
the user physically is at a given hour, for weeks ahead. Identifiers are logged;
content is not. The redaction is by key NAME and runs immediately before the
renderer, so a field added by any later processor is covered too, at every level
including debug.

Event names. ``solve.completed``, not a free-text sentence, so lines aggregate. The
shape is checked in every environment, because ``event`` is the one field present on
every line and the redactor cannot inspect a value it has no key for: an
interpolated ``f"placing {block.title}"`` would otherwise walk a title straight onto
disk. Development and test raise, because a malformed name there is a call-site bug
worth failing on while it is being written. Production does not raise, because the
line is the more useful artifact, so it replaces the name with a fixed event and
carries the original under a redacted key.

Correlation ids propagate through ``structlog.contextvars``, which
``merge_contextvars`` folds onto every line. The HTTP edge binds the id per
request; a worker job binds it per job.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import structlog

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from typing import TextIO

    from structlog.types import EventDict, Processor, WrappedLogger

CORRELATION_ID_KEY = "correlation_id"
TENANT_ID_KEY = "tenant_id"

REDACTED = "[redacted]"

# Environments where a malformed event name raises instead of passing through.
_STRICT_ENVIRONMENTS = frozenset({"development", "test"})

# `solve.completed`, `calendar.sync.rejected`. At least one dot, lowercase.
EVENT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")

# What a malformed event name is replaced with outside development and test. The
# original is carried under a redacted key, so the line survives, the call site is
# findable by querying this event, and an interpolated title cannot reach disk.
MALFORMED_EVENT = "log.malformed_event_name"
MALFORMED_EVENT_KEY = "malformed_event_title"

# Stamps module and line onto a line. Applied ONLY to a quarantined event, because the
# relocated name is redacted and would otherwise identify no call site, and because the
# stack walk should not be paid on every healthy line. `additional_ignores` is what makes
# calling it from inside a processor resolve the caller's frame rather than this module's.
#
# Module and line locate the call uniquely, so the function name is left out: the adder's
# key for it is `func_name`, which the redactor correctly eats as a `_name` suffix. That
# is the accepted cost of treating `name` as content, applied to a field of our own.
_CALLSITE = structlog.processors.CallsiteParameterAdder(
    parameters=(
        structlog.processors.CallsiteParameter.MODULE,
        structlog.processors.CallsiteParameter.LINENO,
    ),
    additional_ignores=[__name__],
)

# Keys whose value is user CONTENT rather than an identifier. Matched exactly or as
# a `_`-suffix, so `block_title` and `anchor_location` are covered too.
#
# `name` is here because the product's Areas, Projects, Habits, Routines, Templates,
# and AnchorTypes all carry user-authored names, and `area_name="Job search"`
# discloses exactly what a block title does. The cost is accepted deliberately: a
# genuinely benign `event_name` or `metric_name` is redacted too, so log the
# identifier instead, which is what every diagnostic question actually needs.
#
# `label` is here for the same reason and one of its own: an off-plan period's label is
# the user's own words, and `period_label="Italy"` discloses where they are as plainly
# as an anchor location does.
_CONTENT_KEYS = frozenset({"title", "location", "name", "summary", "description", "notes", "label"})

# Substrings that mark a key as secret-bearing. Matched anywhere in the key, so
# `refresh_token`, `oauth_client_secret`, and `db_password` are all covered.
_SECRET_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "cookie",
    "credential",
    "passwd",
    "password",
    "private_key",
    "secret",
    "signature",
    "token",
)

# Guards against a self-referential structure walking forever. Log payloads are
# shallow by convention; anything past this depth is replaced wholesale.
_MAX_REDACTION_DEPTH = 6

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "warn": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


def is_sensitive_key(key: str) -> bool:
    """True if a field with this name must never carry its value into a log line."""
    lowered = key.lower()
    if lowered in _CONTENT_KEYS or any(lowered.endswith(f"_{name}") for name in _CONTENT_KEYS):
        return True
    return any(fragment in lowered for fragment in _SECRET_KEY_FRAGMENTS)


def _redact_value(value: object, depth: int) -> object:
    if depth > _MAX_REDACTION_DEPTH:
        return REDACTED
    if isinstance(value, dict):
        return _redact_mapping(cast("Mapping[str, object]", value), depth + 1)
    if isinstance(value, list | tuple | set | frozenset):
        return [_redact_value(item, depth + 1) for item in cast("Sequence[object]", value)]
    return value


def _redact_mapping(payload: Mapping[str, object], depth: int) -> dict[str, object]:
    return {
        key: REDACTED if is_sensitive_key(str(key)) else _redact_value(value, depth)
        for key, value in payload.items()
    }


def redact_sensitive(_logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> EventDict:
    """structlog processor: replace every sensitive-keyed value with ``[redacted]``.

    Runs immediately before the renderer, so it also covers fields merged from
    contextvars and fields added by earlier processors.
    """
    return _redact_mapping(event_dict, depth=0)


def validate_event_name(
    _logger: WrappedLogger, _method_name: str, event_dict: EventDict
) -> EventDict:
    """structlog processor: reject a free-text event name. Raises.

    Used in development and test, where a malformed name is a call-site bug worth
    failing on while it is being written.
    """
    event = event_dict.get("event")
    if isinstance(event, str) and not EVENT_NAME_PATTERN.fullmatch(event):
        raise ValueError(
            f"log event name {event!r} is not a dotted stable name "
            "(expected e.g. 'solve.completed')"
        )
    return event_dict


def quarantine_event_name(
    _logger: WrappedLogger, _method_name: str, event_dict: EventDict
) -> EventDict:
    """structlog processor: move a free-text event name out of ``event``. Never raises.

    Used outside development and test. ``event`` is the one field on every line, and
    the redactor works by key name, so an interpolated event carries whatever the
    call site interpolated straight to disk. Relocating a malformed name under a
    redacted key keeps the line, makes every offending call site findable by querying
    one event, and closes the leak without raising inside the logging path.

    The module and line number of the offending call are added too, because the
    relocated name is redacted and so says nothing about where it came from.
    """
    event = event_dict.get("event")
    if isinstance(event, str) and not EVENT_NAME_PATTERN.fullmatch(event):
        event_dict["event"] = MALFORMED_EVENT
        event_dict[MALFORMED_EVENT_KEY] = event
        _CALLSITE(_logger, _method_name, event_dict)
    return event_dict


def build_processors(*, strict_event_names: bool) -> list[Processor]:
    """The ordered processor chain. Redaction is always the step before rendering.

    The event-name step sits before redaction on purpose, so a quarantined name is
    redacted by the same pass that redacts every other content key. The callsite
    parameters come after it, so a quarantined line names the module and line that
    produced it: without them, "one query finds every offending call site" would find
    the lines but not the sites.
    """
    return [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        validate_event_name if strict_event_names else quarantine_event_name,
        redact_sensitive,
        structlog.processors.JSONRenderer(),
    ]


def configure_logging(*, environment: str, log_level: str, stream: TextIO | None = None) -> None:
    """Configure structlog for this process. Calling it again replaces the config.

    ``stream`` defaults to stdout, where a container collects it. It is a
    parameter so a test can assert against the real rendered line rather than a
    captured intermediate.
    """
    structlog.configure(
        processors=build_processors(strict_event_names=environment.lower() in _STRICT_ENVIRONMENTS),
        wrapper_class=structlog.make_filtering_bound_logger(
            _LEVELS.get(log_level.lower(), logging.INFO)
        ),
        logger_factory=structlog.WriteLoggerFactory(file=stream or sys.stdout),
        # A cached bound logger would keep the previous configuration's chain, so
        # a reconfiguration (a test switching stream or level) would not take.
        cache_logger_on_first_use=False,
    )


def get_logger(service: str) -> structlog.stdlib.BoundLogger:
    """Return a logger with the ``service`` field bound onto every line.

    The initial value is passed to ``get_logger`` rather than applied with a
    following ``.bind()``, because ``.bind()`` materializes the logger against
    whatever configuration exists at that moment. A module-level logger is created
    at import, before :func:`configure_logging` runs, so binding eagerly would
    freeze structlog's default console renderer into every line that logger ever
    emits. Passing initial values keeps the proxy lazy until the first call.
    """
    return cast("structlog.stdlib.BoundLogger", structlog.get_logger(service=service))


def new_correlation_id() -> str:
    """Mint a correlation id (32 lowercase hex chars)."""
    return uuid4().hex


def bind_correlation_id(correlation_id: str) -> None:
    """Bind a correlation id onto every subsequent log line in this context."""
    structlog.contextvars.bind_contextvars(**{CORRELATION_ID_KEY: correlation_id})


def current_correlation_id() -> str | None:
    """The correlation id bound to this context, or ``None`` outside a request or job."""
    bound = structlog.contextvars.get_contextvars().get(CORRELATION_ID_KEY)
    return bound if isinstance(bound, str) else None


def bind_tenant_id(tenant_id: str) -> None:
    """Bind a tenant id onto every subsequent log line in this context."""
    structlog.contextvars.bind_contextvars(**{TENANT_ID_KEY: tenant_id})


def clear_context() -> None:
    """Drop every bound contextvar.

    A worker context is reused between requests and jobs, so the next unit of
    work must not inherit the previous one's correlation id.
    """
    structlog.contextvars.clear_contextvars()
