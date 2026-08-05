"""The two ways the flow ends without a code, driven directly so no test waits five minutes.

``log_in`` is called here rather than through the process because both cases are about the consent
wait, whose bound is five minutes: a person's, not an agent's. The parameter that shortens it is
the same one the command leaves at its default.
"""

from __future__ import annotations

import threading
from io import StringIO
from typing import TYPE_CHECKING
from urllib.parse import urlencode

import httpx
import pytest

from syncr_cli.auth.discovery import DISCOVERY_PATH, AuthorizationServer
from syncr_cli.auth.flow import log_in
from syncr_cli.auth.session import Session
from syncr_cli.auth.storage import RefreshTokenStore
from syncr_cli.errors import Failure
from syncr_cli.http import Transport
from syncr_cli.notices import Notices
from tests import payloads
from tests.browsers import authorize_parameters
from tests.fake_api import Answer, FakeApi

if TYPE_CHECKING:
    from pathlib import Path


def test_a_consent_nobody_gives_says_nothing_was_authorized(tmp_path: Path) -> None:
    notices = Notices(StringIO())

    with FakeApi() as api, httpx.Client(timeout=5.0) as client:
        api.answer("GET", DISCOVERY_PATH, Answer.json(payloads.metadata(api.base_url)))
        transport = Transport(client)
        server = AuthorizationServer.discover(transport, api.base_url)

        with pytest.raises(Failure, match="nothing was authorized"):
            log_in(
                transport=transport,
                server=server,
                session=_session(transport, server, tmp_path, notices),
                notices=notices,
                open_browser=lambda _url: True,
                consent_timeout_seconds=1,
            )

    assert "Opened a browser" in notices.stated[0]


def test_a_redirect_with_neither_a_code_nor_an_error_is_refused(tmp_path: Path) -> None:
    # A browser that came back empty proves nothing about the flow, and exchanging nothing would be
    # a request with no code in it.
    notices = Notices(StringIO())

    def blank_browser(url: str) -> bool:
        stated = authorize_parameters(url)
        target = f"{stated['redirect_uri']}?{urlencode({'state': stated['state']})}"
        threading.Thread(target=lambda: httpx.get(target, timeout=5.0), daemon=True).start()
        return True

    with FakeApi() as api, httpx.Client(timeout=5.0) as client:
        api.answer("GET", DISCOVERY_PATH, Answer.json(payloads.metadata(api.base_url)))
        transport = Transport(client)
        server = AuthorizationServer.discover(transport, api.base_url)

        with pytest.raises(Failure, match="neither a code nor an error"):
            log_in(
                transport=transport,
                server=server,
                session=_session(transport, server, tmp_path, notices),
                notices=notices,
                open_browser=blank_browser,
                consent_timeout_seconds=5,
            )


def _session(
    transport: Transport, server: AuthorizationServer, tmp_path: Path, notices: Notices
) -> Session:
    return Session(
        transport=transport,
        server=server,
        store=RefreshTokenStore(
            account="http://localhost", file_path=tmp_path / "credentials.json", notices=notices
        ),
    )
