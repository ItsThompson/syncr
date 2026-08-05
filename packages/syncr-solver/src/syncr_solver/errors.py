"""What the solver refuses, and why it refuses rather than correcting.

Every error here means a ``SolveInputs`` carried something no plan can be derived from. That is
a fault in the assembler that built it, and silently correcting one would hide the producer
that answered wrongly while making the document describe a week nobody's data supports.

``DomainError`` is the base for the same reason the domain's own errors take it: each one is a
bad argument, the api maps that category to a status code in one place, and the solver must not
grow a transport concern to report a malformed input.
"""

from __future__ import annotations

from syncr_domain.errors import DomainError


class MaterializeError(DomainError):
    """A resolved input cannot be turned into the block or the slot it describes."""


class SolveError(DomainError):
    """A resolved input names something a solve cannot place, and correcting it would hide why.

    One case reaches it today: a pin naming content the week holds nowhere. The assembler drops a
    pin whose occurrence a reduced cadence no longer produces, so such a pin arriving here is a
    producer that answered wrongly, and honoring nothing while reporting nothing would leave a
    stored pin the plan silently never keeps.
    """
