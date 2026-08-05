"""Keychain backends a test can install: one that works, and one that is not there.

Both are real ``keyring`` backends rather than patched functions, so the code under test calls
``keyring`` exactly as it does on a machine, and the branch it takes is chosen by the same
mechanism the real world chooses it by.
"""

from __future__ import annotations

from keyring.backend import KeyringBackend
from keyring.errors import NoKeyringError

# Above `keyring.backends.fail.Keyring`'s zero, so an explicitly installed backend is the one
# resolved. Nothing here is discovered by entry point; a test installs it.
_PRIORITY = 1.0


class InMemoryKeyring(KeyringBackend):
    """A working keychain that forgets everything when the test ends."""

    priority = _PRIORITY

    # Declared with a type rather than inherited: ``KeyringBackend.__init__`` is unannotated, so a
    # typed test could not construct one of these without it.
    def __init__(self) -> None:
        self.stored: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.stored.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.stored[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if self.stored.pop((service, username), None) is None:
            raise NoKeyringError("nothing stored under that account")


class NoKeychain(KeyringBackend):
    """A machine with no working keychain, which is every headless deployment.

    Raises the error ``keyring`` itself raises there, so the fallback under test is chosen by the
    condition it exists for rather than by a stub of it.
    """

    priority = _PRIORITY

    def __init__(self) -> None:
        """Nothing to set up. Declared for the same reason its sibling's is."""

    def get_password(self, service: str, username: str) -> str | None:
        raise NoKeyringError("no recommended backend was available")

    def set_password(self, service: str, username: str, password: str) -> None:
        raise NoKeyringError("no recommended backend was available")

    def delete_password(self, service: str, username: str) -> None:
        raise NoKeyringError("no recommended backend was available")
