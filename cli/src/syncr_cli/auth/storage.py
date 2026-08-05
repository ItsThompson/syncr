"""Where the refresh token lives: the OS keychain, or a file that says it is not the keychain.

Three rules govern this module and each one is a rule about secrets rather than about storage.

**The refresh token never touches an environment variable or a shell history.** Both are readable
by other processes and both leak into logs, so there is no ``SYNCR_REFRESH_TOKEN`` to read and no
flag that takes one. Nothing here consults the environment for a credential.

**Falling back states that it did.** A silent downgrade of secret storage is worse than a loud
one, so a fallback records a notice the runner writes to stderr and ``auth status`` reports the
store it is actually using.

**The file is created 0600 and written atomically.** Created with the mode rather than chmodded
afterwards, so there is no window where it is readable; replaced rather than truncated, so an
interrupted write cannot leave a half-written credential where a whole one was. A file this store
did not write and whose mode is broader is reported on the read, for the same reason a fallback is.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Final

import keyring
from keyring.errors import KeyringError

if TYPE_CHECKING:
    from syncr_cli.notices import Notices

# The keychain entry's service name. The account is the API URL, so one machine can hold a
# credential for two deployments without either overwriting the other.
KEYRING_SERVICE: Final = "syncr-cli"

CREDENTIALS_FILE_NAME: Final = "credentials.json"
CREDENTIALS_FILE_MODE: Final = 0o600

KEYCHAIN_LOCATION: Final = "the OS keychain"


class RefreshTokenStore:
    """The refresh token for one deployment, wherever this machine can keep it.

    One interface over two stores. The keychain is tried first and the file is what a machine
    with no working keychain gets, which is every headless deployment and any desktop where the
    user declined access. Which one answered is reported, never inferred.
    """

    def __init__(self, *, account: str, file_path: Path, notices: Notices) -> None:
        self._account = account
        self._file = _FileStore(file_path, notices)
        self._notices = notices
        self._using_file = False

    @property
    def location(self) -> str:
        """Where this store is keeping the token, in the words ``auth status`` prints."""
        return str(self._file.path) if self._using_file else KEYCHAIN_LOCATION

    @property
    def fell_back(self) -> bool:
        """Whether the keychain was unavailable and a file is holding the credential."""
        return self._using_file

    def read(self) -> str | None:
        """The stored refresh token, or ``None`` when this machine holds none."""
        if not self._using_file:
            try:
                stored = keyring.get_password(KEYRING_SERVICE, self._account)
            except KeyringError as error:
                self._fall_back(error)
            else:
                if stored is not None:
                    return stored
        return self._file.read(self._account)

    def write(self, token: str) -> None:
        """Store ``token``, replacing whatever was there."""
        if not self._using_file:
            try:
                keyring.set_password(KEYRING_SERVICE, self._account, token)
            except KeyringError as error:
                self._fall_back(error)
            else:
                return
        self._file.write(self._account, token)

    def clear(self) -> None:
        """Remove the stored token from both stores.

        Both, unconditionally: a machine that fell back once may hold a copy in the file while
        the keychain works again today, and a logout that left either behind would leave a
        credential the user believes they revoked.
        """
        # A keychain with nothing to delete, or no keychain at all, is not a failed logout: the
        # token is gone either way, and the server-side revocation is what makes the grant dead.
        with suppress(KeyringError):
            keyring.delete_password(KEYRING_SERVICE, self._account)
        self._file.clear(self._account)

    def _fall_back(self, error: KeyringError) -> None:
        self._using_file = True
        self._notices.state(
            f"{KEYCHAIN_LOCATION} is not available on this machine ({error.__class__.__name__}: "
            f"{error}), so the refresh token is kept in {self._file.path} with 0600 permissions. "
            "Anyone who can read that file can act as you until you run 'syncr auth logout'."
        )


class _FileStore:
    """The fallback: one JSON object keyed by API URL, mode 0600.

    Every write normalizes the mode, so a file this store has written is 0600. A file it did not
    write may be anything, and a mode broader than 0600 is stated on the read rather than inferred:
    the discipline of this module is that a secret-storage property is announced, and "the file was
    NOT 0600" is exactly as worth announcing as "the file is".
    """

    def __init__(self, path: Path, notices: Notices) -> None:
        self.path = path
        self._notices = notices

    def read(self, account: str) -> str | None:
        stored = self._all()
        value = stored.get(account)
        if value is None:
            return None
        self._state_a_broad_mode()
        return value if isinstance(value, str) else None

    def write(self, account: str, token: str) -> None:
        stored = self._all()
        stored[account] = token
        self._replace(stored)

    def clear(self, account: str) -> None:
        stored = self._all()
        if stored.pop(account, None) is None:
            return
        self._replace(stored)

    def _all(self) -> dict[str, object]:
        """Every credential this file holds, or nothing when it holds none.

        A file that is not readable JSON is treated as holding nothing rather than raising: the
        recovery is to authorize again, and refusing every command until a corrupt credential
        file is deleted by hand would be a worse answer than replacing it.
        """
        try:
            raw = self.path.read_bytes()
        except OSError:
            return {}
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _replace(self, stored: dict[str, object]) -> None:
        """Write the whole mapping atomically, at 0600, creating the directory if needed."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=".credentials-")
        try:
            os.fchmod(handle, CREDENTIALS_FILE_MODE)
            with os.fdopen(handle, "w", encoding="utf-8") as writing:
                json.dump(stored, writing)
            os.replace(temporary, self.path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def _state_a_broad_mode(self) -> None:
        """Say so when the file holding a credential is readable by more than its owner.

        Stated rather than tightened, because the file is the user's: a store that silently changed
        the permissions of a file it did not create would be acting outside what it was asked to do,
        and the next write normalizes the mode anyway.
        """
        try:
            mode = stat.S_IMODE(self.path.stat().st_mode)
        except OSError:
            return
        if mode & ~CREDENTIALS_FILE_MODE:
            self._notices.state(
                f"{self.path} holds a refresh token and its permissions are {mode:04o}, which is "
                f"broader than {CREDENTIALS_FILE_MODE:04o}: anyone who can read it can act as you. "
                "Run 'chmod 600' on it, or 'syncr auth logout' and authorize again."
            )


def credentials_path(config_path: Path) -> Path:
    """Where the fallback file lives: beside the configuration file, not inside it.

    Beside rather than in, because the configuration file is one a user edits and pastes, and a
    credential must not be in a file anyone is invited to share.
    """
    return config_path.parent / CREDENTIALS_FILE_NAME
