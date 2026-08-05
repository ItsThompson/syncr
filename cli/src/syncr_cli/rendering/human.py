"""One result, rendered for a person: dense, mono, tabular figures, no ornament.

Five groups in one order, separated by a blank line: the payload's heading, the verdict, the
operation, the payload's body, and the problem. A command chooses none of that. It builds a
result and this renders it, which is why two commands cannot lay out a verdict differently.

**No progress output and no spinner.** A count that changes, or nothing.

**Words, not color.** A pipe strips color and a pipe does not strip a word, so a conflict, a
pin, and an origin are each named. Nothing here emits an escape sequence.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING, Final

from syncr_cli.wire.verdict import NOTHING_IS_CHOSEN

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_cli.problems import Problem
    from syncr_cli.results import CliResult, DeadlineRenderer, Rendered
    from syncr_cli.wire.operation import Operation
    from syncr_cli.wire.verdict import Verdict

# Where a verdict's provenance tag sits, so the tags line up under each other across reads. A
# longer headline pushes its own tag right rather than being truncated.
TAG_COLUMN: Final = 58

# What the shortfall prose is wrapped to. Fixed rather than read from the terminal width: output
# a caller can diff between runs cannot depend on the size of the window it was printed in.
PROSE_WIDTH: Final = 76

INFEASIBLE_MARKER: Final = "! "
FEASIBLE_MARKER: Final = "  "


def iso_deadline(moment: datetime) -> str:
    """A deadline with no week around it: the instant itself, offset and all.

    What a surface holding no zone map prints. Naming ``Fri 09:00`` needs the zone the user is in
    on that date, and a surface that guessed one would state a wall time nobody's clock showed.
    """
    return moment.isoformat()


def render_human(result: CliResult) -> str:
    """One result as the lines a terminal shows, with a trailing newline."""
    groups = [
        _header(result.data),
        verdict_lines(result.verdict, _deadline_renderer(result.data)),
        operation_lines(result.operation),
        _body(result.data),
        problem_lines(result.problem),
    ]
    body = "\n\n".join("\n".join(group) for group in groups if group)
    return f"{body}\n" if body else ""


def verdict_lines(verdict: Verdict | None, deadline: DeadlineRenderer) -> list[str]:
    """The verdict, its provenance, and every gap it quantified.

    The provenance is printed whatever the verdict says. A capacity check can prove a week
    impossible and cannot prove one possible, so the product never asserts a certainty it does
    not have.
    """
    if verdict is None:
        return []
    marker = INFEASIBLE_MARKER if verdict.is_infeasible else FEASIBLE_MARKER
    headline = f"  {marker}{verdict.headline}"
    lines = [f"{headline.ljust(TAG_COLUMN)}{verdict.tag}".rstrip()]
    for shortfall in verdict.shortfalls:
        rendered = None if shortfall.deadline is None else deadline(shortfall.deadline)
        lines.extend(_wrapped(shortfall.statement(deadline=rendered)))
    if verdict.shortfalls:
        lines.extend(_wrapped(f"{_tradeoffs(verdict.tradeoff_count)} {NOTHING_IS_CHOSEN}"))
    return lines


def operation_lines(operation: Operation | None) -> list[str]:
    """The operation a command dispatched, so a caller can poll without guessing an id."""
    if operation is None:
        return []
    return [f"  {line}" for line in operation.summary.splitlines()]


def problem_lines(problem: Problem | None) -> list[str]:
    """Why a command failed, and what still works.

    The correlation id is printed when the api sent one: it is what turns a reported error into
    a log query, and a user who cannot quote it cannot be helped.
    """
    if problem is None:
        return []
    lines = [f"{problem.title}: {problem.detail}"]
    lines.extend(f"  {failure.field}: {failure.message}" for failure in problem.errors)
    if problem.instance is not None:
        lines.append(f"  correlation id: {problem.instance}")
    return lines


def _tradeoffs(count: int) -> str:
    return "1 tradeoff." if count == 1 else f"{count} tradeoffs."


def _header(data: Rendered | None) -> list[str]:
    return [] if data is None else data.header_lines()


def _body(data: Rendered | None) -> list[str]:
    return [] if data is None else data.body_lines()


def _deadline_renderer(data: Rendered | None) -> DeadlineRenderer:
    return iso_deadline if data is None else data.render_deadline


def _wrapped(sentence: str) -> list[str]:
    """One sentence, wrapped for a page rather than for a window.

    Words are never broken and hyphens are never split, because the sentences here carry values a
    reader has to be able to copy: an RFC 3339 instant is full of hyphens and colons, and a wrap
    that split one would print a deadline nobody can paste.
    """
    return textwrap.wrap(
        sentence,
        width=PROSE_WIDTH,
        initial_indent="    ",
        subsequent_indent="    ",
        break_long_words=False,
        break_on_hyphens=False,
    )
