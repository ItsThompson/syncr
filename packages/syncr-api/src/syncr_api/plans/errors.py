"""The four rejections the plan side raises, and why none is a ``SyncrError``.

A revision reaches storage from a Pydantic model that has already validated it, and every
document-describing column is derived rather than passed in. So a document that cannot
describe itself, and a revision whose columns contradict each other, are both defects in the
writer rather than something a caller can correct. Neither is part of the error vocabulary a
service raises: both render as the generic 500 the catch-all handler produces, and the fault
is logged there.

The third is the read side of the same rule. A stored document is rebuilt through the domain
constructors, so a row whose binding key does not match its kind, or whose identifier is not
one, is refused where it is read. That is also nothing a caller can correct: the row is
already stored and the correct answer is that it describes no week, rather than a value that
pairs with nothing.

They exist as named types rather than as a bare ``ValueError`` so one category of failure
reads one way, and so the message can name the invariant instead of naming a constraint.
The database enforces the same two pairs for every other writer there will ever be,
including a ``psql`` session.
"""

from __future__ import annotations


class PlanDocumentRejected(Exception):
    """A document that cannot describe itself, so no row may be written from it."""


class RevisionRejected(Exception):
    """A revision whose columns contradict each other, so the row may not be written."""


class StoredDocumentCorrupt(Exception):
    """A stored document the domain constructors cannot rebuild, so it describes no week."""


class AdjustmentRejected(Exception):
    """A concession whose per-date reductions no week could honour, so the row is refused.

    The write side of the same rule. A reduction naming a date outside the concession's own week,
    or a figure that is not a positive count of minutes, pairs with no occurrence: stored, it would
    sit on the table claiming to have been honoured while changing nothing. The read side is
    deliberately tolerant and reports what it dropped, because a row already stored has to be
    readable; this is what stops one being written.
    """
