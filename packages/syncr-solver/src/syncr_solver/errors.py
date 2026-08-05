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
