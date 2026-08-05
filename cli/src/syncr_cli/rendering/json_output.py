"""One result, rendered as the JSON an agent parses.

The wrapper's five members are always present and always in this order, so an agent branches on
shape rather than testing for keys, and two invocations of two different commands diff cleanly
against each other.

**``data`` is the api's own object, unmodified.** Re-spelling a payload here would make this a
second contract that has to be kept level with the first, and any member this build does not
read would silently vanish from the output. Instants therefore stay RFC 3339 with an explicit
offset and durations stay integer minutes, because that is what the api emits.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from syncr_cli.problems import Problem
    from syncr_cli.results import CliResult

# Indented, because the output is meant to be diffable between runs and a one-line object diffs
# as one line. An agent parses either.
INDENT = 2


def render_json(result: CliResult) -> str:
    """One result as the JSON document ``--json`` writes, with a trailing newline."""
    document: dict[str, Any] = {
        "ok": result.ok,
        "data": None if result.data is None else result.data.payload,
        "verdict": None if result.verdict is None else result.verdict.payload,
        "operation": None if result.operation is None else result.operation.payload,
        "problem": None if result.problem is None else _problem(result.problem),
    }
    return f"{json.dumps(document, indent=INDENT, ensure_ascii=False)}\n"


def _problem(problem: Problem) -> dict[str, Any]:
    """Problem details as RFC 9457 shapes them: the four required members, then what applies.

    ``instance`` and ``errors`` are omitted when absent rather than carried as null, which is
    what the api's own body does. The wrapper's five members are what an agent tests for; this
    object is the api's shape and follows the api.
    """
    document: dict[str, Any] = {
        "type": problem.type,
        "title": problem.title,
        "status": problem.status,
        "detail": problem.detail,
    }
    if problem.instance is not None:
        document["instance"] = problem.instance
    if problem.errors:
        document["errors"] = [
            {"field": failure.field, "message": failure.message} for failure in problem.errors
        ]
    return document
