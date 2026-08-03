"""The two rejections a plan write raises, and why neither is a ``SyncrError``.

A revision reaches storage from a Pydantic model that has already validated it, and every
document-describing column is derived rather than passed in. So a document that cannot
describe itself, and a revision whose columns contradict each other, are both defects in the
writer rather than something a caller can correct. Neither is part of the error vocabulary a
service raises: both render as the generic 500 the catch-all handler produces, and the fault
is logged there.

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
