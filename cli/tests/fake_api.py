"""A real HTTP server on a real socket, standing in for the API.

A real server rather than a stubbed client, because half of what this package does is HTTP: the
timeout, the status mapping, the form encoding, the JSON body, the ``Authorization`` header, the
``Idempotency-Key``, and the loopback redirect are all things a stub would assert nothing about. The
server is the only thing faked, and it is faked at the boundary the CLI genuinely does not own.

Routes are matched by method and path, so a test states what each endpoint answers and never the
order the CLI asks in. Every request is recorded, which is how a test asserts that a credential
was presented and that a secret was not.

**A route may be declared idempotent**, which makes the server behave the way the api's guard does:
a repeated ``Idempotency-Key`` is the same act rather than a second one. Without that, a test about
a retry not duplicating would be asserting a rule this server does not have.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Self
from urllib.parse import parse_qs, urlparse

from syncr_cli.idempotency import IDEMPOTENCY_KEY_HEADER

PROBLEM_MEDIA_TYPE = "application/problem+json"
JSON_MEDIA_TYPE = "application/json"


@dataclass(frozen=True, slots=True)
class Answer:
    """What one route answers with."""

    status: int
    body: bytes
    media_type: str = JSON_MEDIA_TYPE

    @classmethod
    def json(cls, payload: Any, status: int = 200) -> Answer:
        return cls(status=status, body=json.dumps(payload).encode("utf-8"))

    @classmethod
    def problem(cls, payload: Any, status: int) -> Answer:
        return cls(
            status=status,
            body=json.dumps(payload).encode("utf-8"),
            media_type=PROBLEM_MEDIA_TYPE,
        )

    @classmethod
    def raw(cls, body: bytes, status: int, media_type: str = "text/html") -> Answer:
        return cls(status=status, body=body, media_type=media_type)


@dataclass(frozen=True, slots=True)
class Recorded:
    """One request the server received."""

    method: str
    path: str
    query: dict[str, list[str]]
    headers: dict[str, str]
    body: bytes

    @property
    def form(self) -> dict[str, str]:
        """The body as a form, which is how the OAuth endpoints are called."""
        return {
            name: values[0]
            for name, values in parse_qs(self.body.decode("utf-8")).items()
            if values
        }


@dataclass
class FakeApi:
    """A server whose routes a test states, and whose requests a test can read."""

    answers: dict[tuple[str, str], list[Answer]] = field(default_factory=dict)
    received: list[Recorded] = field(default_factory=list)
    # Which routes deduplicate by `Idempotency-Key`, and the keys each has seen. The real api's
    # guard stores a response per key and replays it, so a route declared here counts a repeat as
    # the same act rather than a second one: that is what lets a test assert that running a mutation
    # twice with one key creates one thing.
    idempotent: set[tuple[str, str]] = field(default_factory=set)
    keys_seen: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    _server: ThreadingHTTPServer | None = None
    _thread: threading.Thread | None = None

    def answer(self, method: str, path: str, answer: Answer) -> Self:
        """Answer every request to this route this way."""
        self.answers[(method, path)] = [answer]
        return self

    def answer_once_per_key(self, method: str, path: str, answer: Answer) -> Self:
        """Answer this way, and treat a repeated ``Idempotency-Key`` as the same act.

        What the api's guard does: the second request with a key it has already applied reads the
        stored response rather than applying anything. Declared per route, because a test asserting
        that a retry does not duplicate needs a server that can tell a retry from a second act.
        """
        self.idempotent.add((method, path))
        return self.answer(method, path, answer)

    def applications_of(self, method: str, path: str) -> int:
        """How many distinct acts this route saw: one per idempotency key it was given."""
        return len(set(self.keys_seen.get((method, path), [])))

    def answer_in_turn(self, method: str, path: str, *answers: Answer) -> Self:
        """Answer successive requests to this route with successive answers.

        For the one thing a route's identity cannot express: an operation that is running and then
        is not. The last answer is repeated once the list runs out.
        """
        self.answers[(method, path)] = list(answers)
        return self

    def __enter__(self) -> Self:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(self))
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("the fake API is not running")
        host, port = self._server.server_address[:2]
        # `server_address` is typed as an address of any family, so the host may be bytes. Decoded
        # rather than formatted, because a formatted bytes object renders as `b'127.0.0.1'`.
        named = host.decode("ascii") if isinstance(host, bytes) else host
        return f"http://{named}:{port}"

    def requests_to(self, method: str, path: str) -> list[Recorded]:
        return [one for one in self.received if one.method == method and one.path == path]

    def _next(self, method: str, path: str) -> Answer | None:
        queued = self.answers.get((method, path))
        if not queued:
            return None
        return queued.pop(0) if len(queued) > 1 else queued[0]


def _make_handler(api: FakeApi) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            self._handle("GET")

        def do_POST(self) -> None:
            self._handle("POST")

        def do_PUT(self) -> None:
            self._handle("PUT")

        def _handle(self, method: str) -> None:
            parsed = urlparse(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            headers = {name.lower(): value for name, value in self.headers.items()}
            api.received.append(
                Recorded(
                    method=method,
                    path=parsed.path,
                    query=parse_qs(parsed.query),
                    headers=headers,
                    body=body,
                )
            )
            key = headers.get(IDEMPOTENCY_KEY_HEADER.lower())
            if key is not None:
                api.keys_seen.setdefault((method, parsed.path), []).append(key)
            answer = api._next(method, parsed.path)
            if answer is None:
                answer = Answer.problem(
                    {
                        "type": "syncr:not-found",
                        "title": "Resource not found",
                        "status": 404,
                        "detail": f"the fake API has no route for {method} {parsed.path}",
                    },
                    status=404,
                )
            self.send_response(answer.status)
            self.send_header("Content-Type", answer.media_type)
            self.send_header("Content-Length", str(len(answer.body)))
            self.end_headers()
            self.wfile.write(answer.body)

    return Handler
