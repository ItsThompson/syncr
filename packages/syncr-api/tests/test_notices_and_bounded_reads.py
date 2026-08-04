"""The notice contract's one type rule, and the reading of a bounded body.

Both are shared primitives with exactly one interesting property each, so they are asserted here
rather than left to be exercised incidentally by the feature that introduced them.

The notice rule is worth its own test because it is the only place in the api where a schema
refuses a shape a caller could plausibly build: a notice that names what broke and nothing that
survives. The frontend narrows the same field at its own boundary, and this is what stops a
malformed notice reaching that narrowing at all.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from syncr_api.core.http_reads import read_bounded_body
from syncr_api.core.notices import BANNER, OXIDE, Notice, NoticeAction, NoticeScope


def notice(**overrides: object) -> Notice:
    fields: dict[str, object] = {
        "id": "google.write-target-expired.banner",
        "volume": BANNER,
        "pigment": OXIDE,
        "title": "The plan is not reaching your calendar",
        "detail": "Writes have been failing for 2 days.",
        "unavailable": ["Writing the plan to Google"],
        "still_works": ["Reading your calendars"],
    }
    return Notice(**{**fields, **overrides})


def test_a_notice_names_the_capability_that_survives() -> None:
    built = notice(action=NoticeAction(label="Reconnect Google", href="/settings"))

    assert built.still_works == ["Reading your calendars"]
    assert built.action is not None
    assert built.action.label == "Reconnect Google"


def test_a_notice_that_names_no_surviving_capability_is_refused() -> None:
    with pytest.raises(ValidationError, match="names no surviving capability"):
        notice(still_works=[])


def test_only_a_declared_outage_may_name_nothing() -> None:
    # The one shape that legitimately has nothing to say declares itself in a field, so a reader
    # of the code can find the exception rather than infer it from an empty list.
    outage = notice(still_works=[], is_whole_product_down=True)

    assert outage.still_works == []
    assert outage.is_whole_product_down is True


def test_a_notice_renders_camel_case_on_the_wire() -> None:
    # The frontend reads `stillWorks`, and a shape that read two ways would be a contract that
    # drifts.
    rendered = notice(scope=NoticeScope(screen="settings")).model_dump(by_alias=True)

    assert rendered["stillWorks"] == ["Reading your calendars"]
    assert rendered["isWholeProductDown"] is False
    assert rendered["scope"] == {
        "screen": "settings",
        "blockId": None,
        "sourceId": None,
        "date": None,
    }


class _StreamedResponse:
    """A response that yields fixed chunks, which is all the bounded read touches."""

    def __init__(self, *chunks: bytes) -> None:
        self._chunks = chunks

    async def aiter_bytes(self) -> object:
        for chunk in self._chunks:
            yield chunk


async def test_a_body_within_the_bound_is_returned_whole() -> None:
    body = await read_bounded_body(_StreamedResponse(b"abc", b"def"), max_bytes=10)  # type: ignore[arg-type]

    assert body == b"abcdef"


async def test_a_body_over_the_bound_is_refused_rather_than_truncated() -> None:
    # Half a JSON document is not a smaller document, so the answer is None and the caller states
    # the bound. This is the mechanism that stops a provider exhausting the process.
    body = await read_bounded_body(_StreamedResponse(b"abcd", b"efgh"), max_bytes=6)  # type: ignore[arg-type]

    assert body is None


async def test_the_bound_is_applied_while_the_body_arrives() -> None:
    # The chunk that crosses the bound stops the read, so the chunks after it are never pulled.
    pulled: list[bytes] = []

    class _Watched(_StreamedResponse):
        async def aiter_bytes(self) -> object:
            for chunk in (b"1" * 8, b"2" * 8, b"3" * 8):
                pulled.append(chunk)
                yield chunk

    assert await read_bounded_body(_Watched(), max_bytes=10) is None  # type: ignore[arg-type]
    assert len(pulled) == 2
