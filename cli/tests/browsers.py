"""Browsers a test can hand the flow, standing where a real one stands.

A browser is what takes the authorize URL and makes the code arrive on the loopback listener, so a
test that drives the whole flow has to do exactly that. Each one delivers from a thread, because
the listener blocks the thread it runs on.

The authorize URL is read rather than guessed: the redirect and the state are parameters this run
generated, and a fake browser that invented either would be testing itself.

``opens`` is what ``webbrowser.open`` answers. False is a headless machine, where the flow prints
the URL and keeps waiting: the user opens it elsewhere, which these still model by delivering.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

if TYPE_CHECKING:
    from collections.abc import Callable

    from syncr_cli.runtime import BrowserOpener

CODE = "syncrc_the_single_use_code"  # pragma: allowlist secret


def approving_browser(
    *,
    opens: bool = True,
    code: str = CODE,
    state: str | None = None,
    calls: list[str] | None = None,
) -> BrowserOpener:
    """A browser that lands on the consent screen and approves it.

    ``state`` overrides the one the flow generated, which is how the mismatch a hijacked redirect
    would produce is driven.
    """
    return _browser(
        opens=opens,
        calls=calls,
        query=lambda stated: {"code": code, "state": state or stated["state"]},
    )


def refusing_browser(
    *,
    error: str,
    description: str,
    echo_state: bool = True,
    calls: list[str] | None = None,
) -> BrowserOpener:
    """A browser the Authorization Server sent back with a refusal instead of a code.

    ``echo_state`` is what distinguishes a refusal from a hijacked redirect. RFC 6749 requires the
    state on an error redirect, so a conforming server echoes it; a client that checked the state
    first would report a mismatch instead of the server's own reason for anything that did not.
    """

    def query(stated: dict[str, str]) -> dict[str, str]:
        refusal = {"error": error, "error_description": description}
        return {**refusal, "state": stated["state"]} if echo_state else refusal

    return _browser(opens=True, calls=calls, query=query)


def silent_browser(*, calls: list[str] | None = None) -> BrowserOpener:
    """A browser that opens and never comes back, so the wait itself is what is under test."""
    return _browser(opens=True, calls=calls, query=None)


def authorize_parameters(url: str) -> dict[str, str]:
    """The query the flow put on the authorize URL, for a test that asserts it."""
    return {name: values[0] for name, values in parse_qs(urlparse(url).query).items() if values}


def _browser(
    *,
    opens: bool,
    calls: list[str] | None,
    query: Callable[[dict[str, str]], dict[str, str]] | None,
) -> BrowserOpener:
    def open_url(url: str) -> bool:
        if calls is not None:
            calls.append(url)
        if query is not None:
            stated = authorize_parameters(url)
            _deliver(stated["redirect_uri"], query(stated))
        return opens

    return open_url


def _deliver(redirect_uri: str, query: dict[str, str]) -> None:
    def ask() -> None:
        httpx.get(f"{redirect_uri}?{urlencode(query)}", timeout=5.0)

    threading.Thread(target=ask, daemon=True).start()
