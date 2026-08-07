"""The one place this package speaks HTTP, and the one place a response becomes an error.

Two failures are answered here and nowhere else. A request that never got an answer -- no
connection, no name, no reply inside the timeout -- is the API being unavailable, which is its
own exit code because it says "come back later" rather than "you asked wrongly". A request that
got an answer with a failing status carries problem details, which are reported verbatim: the
api composes a detail that names what still works, and re-wording it here would lose that.

**A form body and a JSON body are two methods rather than one with a flag.** The OAuth endpoints
take ``application/x-www-form-urlencoded`` because RFC 6749 says so, and every product mutation
takes JSON. A caller states which by the method it calls, so no request can be sent with the wrong
encoding for its endpoint.

**A failure says what it can truthfully say about the request's effect.** A read that never answered
changed nothing. A write that timed out may have been applied before the answer went missing, so it
says the outcome cannot be told from here and that retrying with the same key is safe: this is the
surface whose whole premise is that an agent reads the sentence, and "nothing was changed" beside a
task that now exists is the one kind of wrong that surface cannot afford.

**Nothing here writes a credential anywhere.** The bearer token is attached to the request and
never appears in a message, a repr, or an exception. A transport failure names the method and the
URL, and a URL this package builds carries no secret: the authorization code and the refresh
token both travel in a form body.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

import httpx

from syncr_cli.errors import OUTCOME_UNKNOWN, ApiRefused, ApiUnreachable, MalformedResponse
from syncr_cli.problems import read_problem

if TYPE_CHECKING:
    from collections.abc import Mapping

# The methods that cannot have changed anything, so a failure on one may say so. Every other method
# may have been applied before the answer went missing, and `OUTCOME_UNKNOWN` is what those say.
SAFE_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})

NOTHING_WAS_CHANGED: Final = "Nothing was changed."

# How long any single request may take. Not the same figure as the operation-wait timeout, which
# bounds a poll loop rather than one exchange: a read is budgeted in hundreds of milliseconds and
# a solve request answers immediately with an operation to follow.
REQUEST_TIMEOUT_SECONDS: Final = 30.0

# What every request identifies itself as, so an operator reading an access log can tell this
# client from the browser.
USER_AGENT: Final = "syncr-cli"

_SUCCESS = range(200, 300)


class Transport:
    """Sends one request and answers with parsed JSON, or raises.

    Wraps ``httpx`` rather than extending it, so every caller in this package gets the same
    timeout, the same error mapping, and the same headers without restating them. The client is
    injected so a test drives a real server over a real socket, or a stub over none.
    """

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    @classmethod
    def opened(cls) -> Transport:
        """A transport against the network, with this package's timeout and headers."""
        return cls(
            httpx.Client(
                timeout=REQUEST_TIMEOUT_SECONDS,
                headers={"User-Agent": USER_AGENT},
                follow_redirects=False,
            )
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Transport:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """A read, as a parsed JSON document."""
        return self._json(self._send("GET", url, params=params, headers=headers))

    def post_json(
        self,
        url: str,
        body: Mapping[str, Any],
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """A JSON write, which is what every product mutation takes."""
        return self._json(self._send("POST", url, body=body, params=params, headers=headers))

    def put_json(
        self, url: str, body: Mapping[str, Any], *, headers: Mapping[str, str] | None = None
    ) -> Any:
        """A JSON replacement, which is what recording a block's outcome is."""
        return self._json(self._send("PUT", url, body=body, headers=headers))

    def post_form(
        self, url: str, form: Mapping[str, str], *, headers: Mapping[str, str] | None = None
    ) -> Any:
        """A form-encoded write, which is what the OAuth endpoints take."""
        return self._json(self._send("POST", url, form=form, headers=headers))

    def post_form_ignoring_body(
        self, url: str, form: Mapping[str, str], *, headers: Mapping[str, str] | None = None
    ) -> None:
        """A form-encoded write whose success carries no body, such as revocation."""
        self._send("POST", url, form=form, headers=headers)

    def _send(
        self,
        method: str,
        url: str,
        *,
        form: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        try:
            response = self._client.request(
                method,
                url,
                data=form,
                json=body,
                params=params,
                headers=dict(headers or {}),
            )
        except httpx.TimeoutException as error:
            raise ApiUnreachable(
                f"{method} {url} did not answer within {REQUEST_TIMEOUT_SECONDS:.0f}s. "
                f"{_effect_of(method)} The API may be starting or overloaded; retry shortly."
            ) from error
        except httpx.HTTPError as error:
            raise ApiUnreachable(
                f"{method} {url} could not be reached: {error}. Nothing was changed. Check "
                "api_url and that the deployment is up."
            ) from error
        if response.status_code not in _SUCCESS:
            raise ApiRefused(read_problem(response.status_code, response.content))
        return response

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return json.loads(response.content)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise MalformedResponse(
                f"{response.request.method} {response.request.url} answered "
                f"{response.status_code} with a body that is not JSON. "
                f"{_effect_of(response.request.method)}"
            ) from error


def _effect_of(method: str) -> str:
    """What a failure on ``method`` may truthfully claim about the request's effect.

    A ``GET`` that never answered changed nothing and can say so. A ``POST`` that timed out may have
    been applied before the answer went missing, so claiming otherwise would be a false statement to
    the one reader that acts on it.
    """
    return NOTHING_WAS_CHANGED if method.upper() in SAFE_METHODS else OUTCOME_UNKNOWN
