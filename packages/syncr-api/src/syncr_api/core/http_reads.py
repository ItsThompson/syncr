"""Reading a response body with a hard size bound, in one place.

Every response syncr reads from a third party is as large as that third party decides. A body
read without a bound is a process another operator can exhaust: an ICS publisher that streams
without end, a token endpoint behind a proxy answering a megabyte of HTML, a paginated calendar
read whose page is larger than the API documents.

So the bound is applied while the body arrives rather than after it has arrived, and it is a
constructor of the answer rather than a check a caller remembers: ``None`` means "larger than you
allow", and the caller decides what that means for its own contract.

The bound is per read and is passed in. What is safe for a calendar feed is not what is safe for
a token response, and a single shared number would be the larger of the two.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx


async def read_bounded_body(response: httpx.Response, *, max_bytes: int) -> bytes | None:
    """The streamed body, or ``None`` once it exceeds ``max_bytes``.

    The response must have been opened as a stream; a body already read into memory was never
    bounded, which is the failure this exists to prevent.
    """
    chunks: list[bytes] = []
    read = 0
    async for chunk in response.aiter_bytes():
        read += len(chunk)
        if read > max_bytes:
            return None
        chunks.append(chunk)
    return b"".join(chunks)
