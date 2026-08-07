"""What the task and backlog commands answer with, in both renderings.

Three shapes: the backlog a read selected, a task just captured, and a task just completed. The two
mutations answer with the task as the api now holds it, so a caller reads what it wrote rather than
what it sent.

**The at-risk count is printed and never derived.** A task is at risk when the feasibility probe
reports a deadline shortfall naming it, so the figure is the server's determination; a client that
compared a deadline against a capacity of its own would put a task at risk on one surface and fine
on another.

**A deadline is printed as the instant it is.** The backlog carries no zone map -- a task belongs to
no week -- so naming ``Fri 09:00`` would state a wall time in a zone this surface cannot speak for.
The instant carries its own offset, which is what makes it unambiguous and diffable between runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from syncr_cli.rendering.durations import duration_column_width, minutes_cell
from syncr_cli.rendering.human import iso_deadline
from syncr_cli.rendering.views import PlainView

if TYPE_CHECKING:
    from syncr_cli.wire.reading import JsonMapping
    from syncr_cli.wire.task import Backlog, Task

# What separates the counts on the header line, wide enough that the eye reads figures rather than a
# sentence. The ledger's own separator, because the two surfaces are one product.
GAP: Final = "    "

ROW_INDENT: Final = "   "
COLUMN_SEPARATOR: Final = "  "

# How wide the title column is padded to, so the words after it line up down the page. A longer
# title pushes its own columns right rather than being truncated.
TITLE_COLUMN_LIMIT: Final = 34

# What a backlog with nothing in it says. A blank body would leave a reader wondering whether the
# read failed.
NOTHING_CAPTURED: Final = "nothing captured"

# What a row reads where an Area was not named by this read.
NO_AREA: Final = "--"

DUE: Final = "due "

# The word a row carries when the current verdict reports a deadline shortfall naming the task. A
# word rather than a color or a symbol: a pipe strips both and does not strip a word.
AT_RISK: Final = "at risk"


@dataclass(frozen=True, slots=True)
class BacklogView(PlainView):
    """The backlog as a ledger: the counts the server computed, then one row per task.

    ``area_names`` is a separate read for the reason the week's ledger takes one: a task carries the
    Area it is charged to as an identifier, and a column of identifiers is not a ledger.
    """

    backlog: Backlog
    area_names: dict[str, str] = field(default_factory=dict)

    @property
    def payload(self) -> JsonMapping:
        return self.backlog.payload

    def header_lines(self) -> list[str]:
        counts = [
            f"{self.backlog.open_count} open",
            f"{self.backlog.at_risk_count} at risk",
            f"{len(self.backlog.tasks)} {_plural('task', len(self.backlog.tasks))} shown",
        ]
        return ["  " + GAP.join(counts)]

    def body_lines(self) -> list[str]:
        if not self.backlog.tasks:
            return [f"{ROW_INDENT}{NOTHING_CAPTURED}"]
        width = duration_column_width([task.remaining_minutes for task in self.backlog.tasks])
        areas = max(
            (len(_area_cell(task, self.area_names)) for task in self.backlog.tasks),
            default=len(NO_AREA),
        )
        return [self._row(task, width=width, areas=areas) for task in self.backlog.tasks]

    def _row(self, task: Task, *, width: int, areas: int) -> str:
        """One task: the work left, the Area, the title, then the words."""
        row = (
            f"{ROW_INDENT}{minutes_cell(task.remaining_minutes, width)}{COLUMN_SEPARATOR}"
            f"{_area_cell(task, self.area_names).ljust(areas)}{COLUMN_SEPARATOR}"
            f"{task.title.ljust(min(TITLE_COLUMN_LIMIT, _widest_title(self.backlog)))}"
        )
        for marker in _markers(task):
            row = f"{row}{COLUMN_SEPARATOR}{marker}"
        return row.rstrip()


@dataclass(frozen=True, slots=True)
class TaskView(PlainView):
    """One task, as the api now holds it. What a capture and a completion both answer with.

    One shape for both, because both answer with the same resource and the lead word is the only
    difference: a second view would be a second rendering of one thing.
    """

    task: Task
    did: str

    @property
    def payload(self) -> JsonMapping:
        return self.task.payload

    def header_lines(self) -> list[str]:
        lines = [
            f"{self.did} {self.task.title}",
            f"  {self.task.id}",
            f"  {minutes_cell(self.task.remaining_minutes).strip()} left of "
            f"{minutes_cell(self.task.estimate_minutes).strip()}    {self.task.status}"
            f"    {self.task.priority}",
        ]
        if self.task.deadline is not None:
            lines.append(f"  {DUE}{iso_deadline(self.task.deadline)}")
        return lines


def _markers(task: Task) -> list[str]:
    """The words a task's row carries: its status, its priority, its deadline, and its risk.

    Words rather than color, and never a symbol: a pipe strips color and a pipe does not strip a
    word, which is the rule every surface in this product follows.
    """
    markers = [task.status, task.priority]
    if task.deadline is not None:
        markers.append(f"{DUE}{iso_deadline(task.deadline)}")
    if task.at_risk:
        markers.append(AT_RISK)
    return markers


def _area_cell(task: Task, area_names: dict[str, str]) -> str:
    """The Area column for one row, or no Area where this read did not name one."""
    return area_names.get(task.area_id, NO_AREA)


def _widest_title(backlog: Backlog) -> int:
    return max((len(task.title) for task in backlog.tasks), default=0)


def _plural(word: str, count: int) -> str:
    return word if count == 1 else f"{word}s"
