"""Putting a credential where a machine with no keychain keeps one.

Three suites need a refresh token already stored: one to drive a command without running the whole
flow first, one to reach the exit-code cases, and one to prove the credential is presented. All
three seeded it themselves, which is how three copies of one path came to exist.

The file is where :mod:`syncr_cli.auth.storage` looks and at the mode it writes, so what a test
seeds is what the store would have written rather than something it happens to accept.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final

from syncr_cli.auth.storage import CREDENTIALS_FILE_NAME

if TYPE_CHECKING:
    from pathlib import Path

# A stored refresh token, in the shape the api mints one. Not a secret: nothing verifies it, and the
# fake token endpoint answers whatever it is presented.
STORED_REFRESH: Final = "syncrr_stored"  # pragma: allowlist secret

# What `keyring` resolves to in a process with no keychain, which is what a headless machine has and
# what makes the file below the store rather than a fallback nobody reaches.
NO_KEYCHAIN: Final = {"PYTHON_KEYRING_BACKEND": "keyring.backends.fail.Keyring"}


def credentials_file(home: Path) -> Path:
    """Where the store keeps a refresh token when this machine has no keychain."""
    return home / ".config" / "syncr" / CREDENTIALS_FILE_NAME


def seed_refresh_token(home: Path, api_url: str, *, token: str = STORED_REFRESH) -> Path:
    """Put a refresh token for ``api_url`` where the store will find it, at the mode it writes."""
    path = credentials_file(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({api_url: token}), encoding="utf-8")
    path.chmod(0o600)
    return path
