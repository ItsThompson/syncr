"""The signing-key rotation command.

Rotation is a deliberate act, not something a process does on its own. This command reads the
encrypted key file, promotes the current key to previous, generates a new current key, and
replaces the file atomically. The api reads the file at startup and never again, so the new key
takes effect when the process restarts: until then the old key is still signing, and after the
restart the old key is still VERIFYING, which is what makes a rotation invisible to a client
holding a token minted a moment before it.

It is also how the file is created. A fresh deployment runs this once, with nothing at the
path, and gets a key set with a current key and no previous one.

``docs/runbooks/rotate-oauth-signing-key.md`` states when to run it and how to confirm it
worked.
"""

from __future__ import annotations

import sys
from pathlib import Path

from syncr_api.core.settings import API_SERVICE, EnvSettings, build_service_settings
from syncr_api.oauth.config import build_oauth_config
from syncr_api.oauth.keys import read_key_file, rotate, write_key_file
from syncr_common.logging import configure_logging, get_logger

# Exit codes, so a deploy script can branch on the outcome: 0 rotated, 1 refused.
EXIT_OK = 0
EXIT_REFUSED = 1

NO_PATH_CONFIGURED = (
    "OAUTH_KEYS_PATH is empty, so there is nowhere to write the signing keys. Set it to a "
    "path this process can write and the api process can read, for example "
    "OAUTH_KEYS_PATH=/var/lib/syncr/oauth-signing-keys.enc"
)

_log = get_logger("syncr.oauth")


def rotate_signing_keys(path: Path, encryption_key: str) -> tuple[str, str | None]:
    """Rotate the key set at ``path``, and return the new and retired key identifiers.

    Reads before writing, and writes through a temporary file that replaces the original only
    once it is complete, so an interrupted rotation leaves the previous key set intact rather
    than a file the api cannot parse.
    """
    existing = read_key_file(path, encryption_key) if path.exists() else None
    rotated = rotate(existing)
    write_key_file(path, encryption_key, rotated)
    return rotated.current.kid, rotated.previous.kid if rotated.previous else None


def main() -> None:
    """The console entrypoint. Refuses rather than guessing when no path is configured."""
    env = EnvSettings()
    settings = build_service_settings(service=API_SERVICE, env=env)
    configure_logging(environment=settings.environment, log_level=settings.log_level)
    config = build_oauth_config(settings, is_dev=env.is_dev)
    if not config.keys_path:
        print(f"refused: {NO_PATH_CONFIGURED}", file=sys.stderr)
        raise SystemExit(EXIT_REFUSED)

    path = Path(config.keys_path)
    created = not path.exists()
    current, previous = rotate_signing_keys(path, config.key_encryption_key)
    _log.info("oauth.keys.rotated", created=created, current_kid=current, previous_kid=previous)
    action = "created" if created else "rotated"
    print(
        f"{action} {path}\n"
        f"  signing key   {current}\n"
        f"  still trusted {previous or 'none: this is the first key'}\n"
        "restart the api so it reads the new key set: the old one keeps verifying until "
        "every token it signed has expired."
    )
    raise SystemExit(EXIT_OK)
