"""The loopback listener: what it binds, what it accepts, and what it refuses.

Driven with real HTTP requests to a real ephemeral port, because everything worth asserting here is
a property of the socket and the request: which interface it binds, that a second path does not end
the wait, and that a browser gets an answer it can read.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import httpx
import pytest

from syncr_cli.auth.loopback import (
    CALLBACK_PATH,
    LOOPBACK_HOST,
    LoopbackReceiver,
    Redirected,
    require_expected_state,
)
from syncr_cli.errors import Failure, UsageError

if TYPE_CHECKING:
    from collections.abc import Iterator

STATE = "this-runs-nonce"
CODE = "syncrc_the_single_use_code"  # pragma: allowlist secret


@pytest.fixture
def receiver() -> Iterator[LoopbackReceiver]:
    with LoopbackReceiver() as listening:
        yield listening


def test_the_redirect_is_loopback_with_an_ephemeral_port(receiver: LoopbackReceiver) -> None:
    # RFC 8252 requires the Authorization Server to accept any port on a loopback redirect, and a
    # fresh one per run is what stops two logins colliding. Bound to loopback only, so no other
    # machine can deliver the code.
    assert receiver.redirect_uri.startswith(f"http://{LOOPBACK_HOST}:")
    assert receiver.redirect_uri.endswith(CALLBACK_PATH)
    assert int(receiver.redirect_uri.split(":")[2].split("/")[0]) > 0


def test_a_code_arrives_on_the_callback(receiver: LoopbackReceiver) -> None:
    answered = _request_in_background(f"{receiver.redirect_uri}?code={CODE}&state={STATE}")

    received = receiver.wait(timeout_seconds=5)
    answered.join(timeout=5)

    assert received.code == CODE
    assert received.state == STATE
    assert received.error is None


def test_the_browser_is_told_it_can_close_the_window(receiver: LoopbackReceiver) -> None:
    answers: list[httpx.Response] = []
    answered = _request_in_background(f"{receiver.redirect_uri}?code={CODE}&state={STATE}", answers)

    receiver.wait(timeout_seconds=5)
    answered.join(timeout=5)

    assert answers[0].status_code == 200
    assert "close this window" in answers[0].text
    assert answers[0].headers["Cache-Control"] == "no-store"


def test_a_refusal_delivered_on_the_redirect_arrives_as_itself(
    receiver: LoopbackReceiver,
) -> None:
    # An unregistered scope arrives this way rather than as a body, which is what lets a waiting
    # CLI fail immediately instead of at its timeout.
    answered = _request_in_background(
        f"{receiver.redirect_uri}?error=invalid_scope&error_description=admin+is+refused"
        f"&state={STATE}"
    )

    received = receiver.wait(timeout_seconds=5)
    answered.join(timeout=5)

    assert received.error == "invalid_scope"
    assert received.error_description == "admin is refused"
    assert received.code is None


def test_a_request_to_another_path_does_not_end_the_wait(receiver: LoopbackReceiver) -> None:
    # A browser asks for a favicon. Treating the first request as the answer would abandon the
    # flow before the user had pressed anything.
    base = receiver.redirect_uri.rsplit(CALLBACK_PATH, 1)[0]
    answers: list[httpx.Response] = []
    asking = _request_in_background(
        f"{base}/favicon.ico",
        answers,
        then=f"{receiver.redirect_uri}?code={CODE}&state={STATE}",
    )

    received = receiver.wait(timeout_seconds=5)
    asking.join(timeout=5)

    assert answers[0].status_code == 404
    assert received.code == CODE


def test_a_wait_that_nobody_answers_says_where_it_was_waiting(
    receiver: LoopbackReceiver,
) -> None:
    with pytest.raises(Failure) as timed_out:
        receiver.wait(timeout_seconds=1)

    assert receiver.redirect_uri in str(timed_out.value)
    assert "nothing was authorized" in str(timed_out.value)


def test_a_redirect_carrying_someone_elses_state_is_refused() -> None:
    with pytest.raises(UsageError, match="state this run did not send"):
        require_expected_state(
            Redirected(code=CODE, state="another-flow", error=None, error_description=None), STATE
        )


def test_a_redirect_carrying_this_runs_state_is_accepted() -> None:
    require_expected_state(
        Redirected(code=CODE, state=STATE, error=None, error_description=None), STATE
    )


def _request_in_background(
    url: str, answers: list[httpx.Response] | None = None, *, then: str | None = None
) -> threading.Thread:
    """Ask for ``url`` from another thread, because the receiver blocks on the main one.

    ``then`` asks for a second URL once the first has been answered, in the same thread, so the
    order the listener sees two requests in is the order the test stated rather than a race.
    """

    def ask() -> None:
        response = httpx.get(url, timeout=5.0)
        if answers is not None:
            answers.append(response)
        if then is not None:
            httpx.get(then, timeout=5.0)

    thread = threading.Thread(target=ask, daemon=True)
    thread.start()
    return thread
