"""The one rejection an operation transition raises, and why it is not a ``SyncrError``.

An operation's status is written by the lifecycle service and by nothing else, and every step it
takes is one the state machine names. A step the machine does not name is therefore a defect in
the caller rather than something a caller can correct: it renders as the generic 500 the catch-all
handler produces, and the fault is logged there.

It exists as a named type rather than as a bare ``ValueError`` so the message can name the step
that was attempted and the status the row was actually in. That pair is what a reader needs: a
transition refused because the row had already moved on is a race, and one refused because the
step does not exist is a bug, and the two read differently only if the message says which.
"""

from __future__ import annotations


class IllegalTransition(Exception):
    """A step the operation state machine does not name, or a row that had already moved on."""
