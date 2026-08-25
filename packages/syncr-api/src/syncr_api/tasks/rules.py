"""What a task has to satisfy before it is stored, and how a domain rejection becomes a status.

Two kinds of rule meet here and they are kept apart on purpose.

The **comparisons between two stored rows** live at the service layer because a request schema
cannot see the second row: whether an Area exists, and whether a Project's Area is the task's
Area. A rule stated in a schema would be a second, weaker statement of one of these.

The **physics** lives in ``syncr_domain.tasks`` and is only MAPPED here. T1 is arithmetic over
two of the task's own numbers, so it is stated once, in the pure package, and this module is
what turns that rejection into the 422 the boundary owes it. That is why there is no comparison
of a chunk against an estimate anywhere in this module or in ``schemas.py``.

The one rejection that is not a 422 is a task that already ended. Completed and dropped say
opposite things, so crossing between them is a conflict with the current state rather than a bad
value in the request.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from syncr_api.core.errors import Conflict, FieldError, ValidationFailed
from syncr_api.tasks.config import TASK_RESOURCE
from syncr_domain.projects import ProjectAreaMismatch
from syncr_domain.snap import SNAP_MINUTES
from syncr_domain.tasks import ChunkLargerThanEstimate, ChunkOffTheGrid, TaskAlreadyEnded

if TYPE_CHECKING:
    from collections.abc import Iterator

PROJECT_RESOURCE = "project"

# The wire spellings, which are what a caller reads in `errors[].field`. camelCase because that
# is what the document advertises and what a generated client sends.
ESTIMATE_FIELD = "estimateMinutes"
MIN_CHUNK_FIELD = "minChunkMinutes"
PROJECT_FIELD = "projectId"


def unknown_project(field: str) -> list[FieldError]:
    """The field-level error a request naming a Project that does not exist carries."""
    return [FieldError(field=field, message=f"No {PROJECT_RESOURCE} matches that identifier.")]


@contextmanager
def stated_rejection() -> Iterator[None]:
    """Turn a domain rejection into the status and the wording the boundary owes it.

    T1 names both numbers rather than one, because it is the PAIR that is unsatisfiable and
    either number can be the one the caller meant to change: a capture usually meant the
    minimum, and a patch that lowered the estimate under a stored minimum usually meant the
    estimate.
    """
    try:
        yield
    except ChunkLargerThanEstimate as error:
        raise ValidationFailed(
            f"That {TASK_RESOURCE} was not accepted: {error}. Nothing was changed. Raise the "
            "estimate or lower the minimum chunk so the smallest placement fits inside the "
            "work. Every other task still reads as it did.",
            errors=[
                FieldError(field=MIN_CHUNK_FIELD, message="It exceeds the estimate."),
                FieldError(field=ESTIMATE_FIELD, message="It is below the minimum chunk."),
            ],
        ) from error
    except ChunkOffTheGrid as error:
        raise ValidationFailed(
            f"That {TASK_RESOURCE} was not accepted: {error}. Nothing was changed. State the "
            f"minimum chunk in whole {SNAP_MINUTES}-minute steps, the grid every placement "
            "lands on. Every other task still reads as it did.",
            errors=[
                FieldError(
                    field=MIN_CHUNK_FIELD, message="It is not a whole number of grid steps."
                ),
            ],
        ) from error
    except ProjectAreaMismatch as error:
        raise ValidationFailed(
            f"That {TASK_RESOURCE} was not accepted: {error}. Nothing was changed. Capture it in "
            "the project's own Area, or clear the project and keep the Area.",
            errors=[
                FieldError(
                    field=PROJECT_FIELD, message="Its Area is not the Area this task claims."
                )
            ],
        ) from error
    except TaskAlreadyEnded as error:
        raise Conflict(
            f"That {TASK_RESOURCE} was not changed: {error}. A completed task is work that "
            "happened and survives in reports, and a dropped one is work that will not, so one "
            "cannot become the other. The task still reads as it did."
        ) from error
