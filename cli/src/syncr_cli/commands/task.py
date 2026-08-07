"""``task add``, ``task list``, and ``task done``.

Three commands over one resource. The two mutations answer with the task as the api now holds it, so
a caller reads what it wrote; both carry an ``Idempotency-Key`` derived from the command and its
arguments, so a retry of the same invocation lands the same row.

**A capture states a title and an Area and nothing else it does not mean.** Every other field has
a documented default the api owns -- the estimate, the minimum chunk, the priority, whether the
task is splittable -- and sending a value for one this caller did not state would make the client a
second statement of a default that has an owner.

**Two identical captures are one task unless the caller says otherwise.** The derived key is the
same for the same arguments, which is what makes a retry safe; an agent that genuinely means two
states ``--idempotency-key`` to say so.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from syncr_cli.areas import area_names
from syncr_cli.arguments import stated_identifier, stated_instant
from syncr_cli.parser import add_verb, register_command
from syncr_cli.rendering.task_views import BacklogView, TaskView
from syncr_cli.results import CliResult
from syncr_cli.wire.task import Backlog, Task

if TYPE_CHECKING:
    import argparse

    from syncr_cli.parser import Invocation, Parser, Verbs
    from syncr_cli.runtime import Runtime
    from syncr_cli.wire.reading import JsonMapping

NOUN = "task"

CAPTURED = "captured"
COMPLETED = "completed"

# The statuses the api's filter accepts. Stated so `--status` refuses a word the api would 422 on,
# with a message naming the three rather than a rejected request.
STATUSES = ("open", "completed", "dropped")


def register(nouns: Verbs, shared: Parser) -> None:
    """Put the three task commands in the catalog."""
    verbs = add_verb(nouns, shared, noun=NOUN, noun_help="Capture, list, and complete tasks")
    add = register_command(
        verbs,
        noun=NOUN,
        verb="add",
        summary=(
            "Capture a task. A title and an Area are required and every other field has a "
            "documented default"
        ),
        handler=capture,
        shared=shared,
        examples=(
            "syncr task add 'Leetcode: graphs' --area 22222222-2222-4222-8222-222222222222",
            "syncr task add 'Write the RFC' --area <area-id> --estimate 180 "
            "--deadline 2026-02-13T09:00:00+00:00",
            "syncr task add 'Two of these' --area <area-id> --idempotency-key second",
        ),
    )
    _capture_arguments(add)
    listing = register_command(
        verbs,
        noun=NOUN,
        verb="list",
        summary="List tasks, with filters. Every status unless one is named",
        handler=listed,
        shared=shared,
        examples=(
            "syncr task list",
            "syncr task list --status open --area <area-id>",
            "syncr task list --json | jq '.data.tasks[].title'",
        ),
    )
    _filter_arguments(listing)
    done = register_command(
        verbs,
        noun=NOUN,
        verb="done",
        summary="Complete a task. It leaves solver eligibility and keeps its recorded time",
        handler=complete,
        shared=shared,
        examples=("syncr task done <task-id>", "syncr task done <task-id> --json"),
    )
    done.add_argument(
        "task_id",
        metavar="TASK_ID",
        type=stated_identifier,
        help="the task to complete, as an earlier response spelled its id",
    )


def capture(runtime: Runtime, invocation: Invocation) -> CliResult:
    """Capture one task and answer with what the api now holds."""
    body = _capture_body(invocation)
    return CliResult.succeeded(
        TaskView(
            task=Task.read_one(
                runtime.client.capture_task(body, key=invocation.idempotency_key(dict(body))),
                "task",
            ),
            did=CAPTURED,
        )
    )


def listed(runtime: Runtime, invocation: Invocation) -> CliResult:
    """Read the tasks a filter selected, and the counts the server computed for them."""
    return CliResult.succeeded(read_backlog(runtime, invocation, status=None))


def read_backlog(runtime: Runtime, invocation: Invocation, *, status: str | None) -> BacklogView:
    """The tasks a filter selected, named and ready to print.

    ``status`` is what the calling command imposes and ``--status`` is what the caller states, so
    ``backlog list`` can ask for the open work while ``task list`` asks for whatever was named.
    """
    return BacklogView(
        backlog=Backlog.read(
            runtime.client.list_tasks(
                area_id=invocation.value("area", str),
                status=invocation.value("status", str) or status,
            )
        ),
        area_names=area_names(runtime.client, runtime.notices),
    )


def complete(runtime: Runtime, invocation: Invocation) -> CliResult:
    """Complete one task and answer with what the api now holds."""
    task_id = invocation.required("task_id", str)
    return CliResult.succeeded(
        TaskView(
            task=Task.read_one(
                runtime.client.complete_task(
                    task_id, key=invocation.idempotency_key({"taskId": task_id})
                ),
                "task",
            ),
            did=COMPLETED,
        )
    )


def _capture_body(invocation: Invocation) -> JsonMapping:
    """The capture request, carrying only what the caller stated.

    An omitted field is omitted rather than sent as null: the api owns each default, and a value
    this client filled in would be a second statement of a rule that has an owner. ``--atomic``
    is the one flag that sends a value for a field it names by its opposite, because ``splittable``
    defaults to true and the useful thing to state is that a task is not.
    """
    body: JsonMapping = {
        "areaId": invocation.required("area", str),
        "title": invocation.required("title", str),
    }
    for field, name in (
        ("estimate_minutes", "estimateMinutes"),
        ("min_chunk_minutes", "minChunkMinutes"),
    ):
        stated_minutes = invocation.value(field, int)
        if stated_minutes is not None:
            body[name] = stated_minutes
    priority = invocation.value("priority", str)
    if priority is not None:
        body["priority"] = priority
    deadline = invocation.value("deadline", datetime)
    if deadline is not None:
        body["deadline"] = deadline.isoformat()
    if invocation.value("atomic", bool):
        body["splittable"] = False
    return body


def _capture_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("title", metavar="TITLE", help="what the work is, in your own words")
    command.add_argument(
        "--area",
        required=True,
        metavar="AREA_ID",
        type=stated_identifier,
        help="the one Area this task's time counts toward. Declared once and never moved",
    )
    command.add_argument(
        "--estimate",
        dest="estimate_minutes",
        type=int,
        metavar="MINUTES",
        help="total work in minutes. The API's own default applies when this is omitted",
    )
    command.add_argument(
        "--deadline",
        type=stated_instant,
        metavar="INSTANT",
        help="when the work is due, with a UTC offset. Read by the feasibility probe, never "
        "enforced: a task with no capacity before it is reported rather than refused",
    )
    command.add_argument(
        "--priority",
        metavar="PRIORITY",
        help="how much the objective prefers this task over another in the same Area",
    )
    command.add_argument(
        "--min-chunk",
        dest="min_chunk_minutes",
        type=int,
        metavar="MINUTES",
        help="the smallest placement a splittable task may be divided into",
    )
    command.add_argument(
        "--atomic",
        action="store_true",
        help="place this task as one block of the whole estimate, or not at all",
    )


def _filter_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--area", metavar="AREA_ID", type=stated_identifier, help="only tasks in this Area"
    )
    command.add_argument(
        "--status", choices=STATUSES, help="only tasks in this status. Every status when omitted"
    )
