"""What one invocation is given: its settings, its streams, and the collaborators it may need.

Assembled once at startup and handed to a command, which is what makes every seam substitutable:
a test supplies its own streams, its own environment, its own clock, and its own transport, and
drives the same code the process does.

**Nothing here is built eagerly except the settings.** A command that answers from its arguments
opens no socket and refreshes no token, so ``syncr auth logout`` on a machine holding nothing
never reaches the network.

**stdout is the result and stderr is everything else.** The TTY reading that chooses the default
output format is taken here, once, from the stream the result will be written to.
"""

from __future__ import annotations

import webbrowser
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import monotonic, sleep
from typing import TYPE_CHECKING, Self

from syncr_cli.api_client import ApiClient
from syncr_cli.auth.discovery import AuthorizationServer
from syncr_cli.auth.session import Session
from syncr_cli.auth.storage import RefreshTokenStore, credentials_path
from syncr_cli.config_file import config_path, default_home, read_config
from syncr_cli.notices import Notices
from syncr_cli.settings import Flags, Settings, resolve_settings

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from datetime import date
    from pathlib import Path
    from typing import TextIO

    from syncr_cli.http import Transport

# How a browser is opened, and the one thing on the machine that is not a stream or a value. A
# member of `Host` rather than a call inside the flow, because a test that drives the redirect has
# to stand where the browser stands.
type BrowserOpener = Callable[[str], bool]

# How a wait passes time and how it tells that time has passed. Members of `Host` for the same
# reason: a test drives a supersession and a timeout in milliseconds rather than waiting for either,
# and the loop it drives is the loop the process runs.
type Sleeper = Callable[[float], None]
type Monotonic = Callable[[], float]


@dataclass(frozen=True, slots=True)
class Host:
    """The machine one invocation runs on, as this package is allowed to see it.

    Every reading of the outside world is a member here rather than a call inside a command, so a
    test states the environment instead of arranging one.
    """

    env: Mapping[str, str]
    home: Path
    stdout: TextIO
    stderr: TextIO
    stdout_is_tty: bool
    today: date
    open_browser: BrowserOpener = webbrowser.open
    sleep: Sleeper = sleep
    monotonic: Monotonic = monotonic

    @classmethod
    def real(cls, stdout: TextIO, stderr: TextIO, env: Mapping[str, str]) -> Self:
        return cls(
            env=env,
            home=default_home(),
            stdout=stdout,
            stderr=stderr,
            stdout_is_tty=_is_tty(stdout),
            # The machine's own date, which is what "the current ISO week" means to the person at
            # the terminal. A machine in a zone ahead of the server's is in a different week for
            # part of a day, and `--week` is how that is stated rather than inferred.
            today=datetime.now(UTC).astimezone().date(),
        )


@dataclass(slots=True)
class Runtime:
    """One invocation's resolved configuration and its lazily built collaborators."""

    host: Host
    settings: Settings
    notices: Notices
    transport: Transport
    _server: AuthorizationServer | None = field(default=None, init=False)
    _store: RefreshTokenStore | None = field(default=None, init=False)
    _session: Session | None = field(default=None, init=False)

    @classmethod
    def build(cls, *, host: Host, flags: Flags, transport: Transport) -> Self:
        path = config_path(dict(host.env), host.home)
        return cls(
            host=host,
            settings=resolve_settings(
                flags=flags,
                env=host.env,
                config=read_config(path),
                stdout_is_tty=host.stdout_is_tty,
                today=host.today,
            ),
            notices=Notices(host.stderr),
            transport=transport,
        )

    @property
    def store(self) -> RefreshTokenStore:
        """Where this machine keeps the refresh token for the configured API."""
        if self._store is None:
            self._store = RefreshTokenStore(
                account=self.settings.api_url,
                file_path=credentials_path(config_path(dict(self.host.env), self.host.home)),
                notices=self.notices,
            )
        return self._store

    @property
    def server(self) -> AuthorizationServer:
        """This deployment's OAuth endpoints, discovered once per invocation."""
        if self._server is None:
            self._server = AuthorizationServer.discover(self.transport, self.settings.api_url)
        return self._server

    @property
    def session(self) -> Session:
        """The bearer credential for this invocation."""
        if self._session is None:
            self._session = Session(transport=self.transport, server=self.server, store=self.store)
        return self._session

    @property
    def client(self) -> ApiClient:
        """The api, with this invocation's credential attached."""
        return ApiClient(
            transport=self.transport, api_url=self.settings.api_url, session=self.session
        )


def _is_tty(stream: TextIO) -> bool:
    """Whether ``stream`` is a terminal.

    A stream that cannot answer is not a terminal. A closed or replaced stdout raises rather than
    answering, and a process whose stdout is gone is certainly not talking to a person.
    """
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False
