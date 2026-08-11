"""Answering a write a unique index refused, in the words the read already had.

Several rules here are stated twice on purpose: a read that refuses the request with a
stated 409, and a unique index that is the real guarantee. The read holds no lock, so two
callers can both pass it, and the one the index then refuses would reach the catch-all
handler and be answered 500 for a request that a moment earlier was answered 409.

:func:`answered_once` closes that without a handler over ``IntegrityError`` as a class,
which could not name which rule was broken. It takes the write, the name of the one index
that write may lose to, and the courtesy read the caller already ran. When that index
refuses the write, the read runs again, sees the row that won, and its own refusal is what
the caller answers with. The two 409s carry one ``type`` and one ``detail`` because one
piece of code raises both, rather than because two messages were kept in step.

Two constraints shape the implementation. Postgres abandons the whole transaction on a
constraint violation, so the write needs a savepoint or the re-read would fail instead of
answering. And asyncpg names the offended constraint on the error it raises, which
SQLAlchemy wraps rather than copies, so the name is read from the wrapped cause.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError

from syncr_api.core.errors import Conflict

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from contextlib import AbstractAsyncContextManager

# Called to open a savepoint the refused write is rolled back to, leaving the transaction
# around it usable. `AsyncSession.begin_nested` is what a request passes.
type Savepoint = Callable[[], AbstractAsyncContextManager[object]]


async def answered_once[ResultT](
    *,
    savepoint: Savepoint,
    index: str,
    write: Callable[[], Awaitable[ResultT]],
    refusal: Callable[[], Awaitable[None]],
) -> ResultT:
    """Perform ``write``, and answer a refusal from ``index`` with ``refusal``'s own words.

    ``refusal`` is the courtesy read the caller took before the write, so calling it again
    is what makes the raced answer and the read's answer the same answer. It is expected to
    raise: when it does not, the row that refused the write has been removed since, and the
    caller is asked to send the request again rather than handed a fault it did not cause.

    A refusal from any other constraint is left alone, so each rule is still named by
    whoever owns it.
    """
    try:
        async with savepoint():
            return await write()
    except IntegrityError as error:
        if refused_index(error) != index:
            raise
        await refusal()
        raise Conflict(
            "Another request changed the same thing while this one was being answered, and "
            "what it collided with is already gone. Nothing was changed. Send the request "
            "again: nothing about it was wrong."
        ) from error


def refused_index(error: IntegrityError) -> str | None:
    """The constraint the database blamed for this refusal, or ``None`` if it named none."""
    named = getattr(getattr(error.orig, "__cause__", None), "constraint_name", None)
    return named if isinstance(named, str) else None
