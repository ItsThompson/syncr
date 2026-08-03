"""Export the app's OpenAPI document to a file.

The frontend never hand-writes a response type: it consumes types generated from this
document, so the document is the contract and it is committed. ``just contract``
regenerates it and then regenerates ``frontend/src/api/schema.d.ts`` from it, and a CI
job runs both and fails on a diff. A backend change that alters the contract therefore
cannot merge without the frontend seeing it.

The document must depend on the routes and schemas ONLY, never on the machine it was
generated on, or the CI diff turns into noise and stops being a signal. So settings are
constructed here with fixed values rather than read from the environment, and the
document is serialised with sorted keys and a trailing newline.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import SecretStr

from syncr_api.core.app_factory import create_app
from syncr_api.core.settings import API_PORT, API_SERVICE, ServiceSettings
from syncr_api.oauth.config import build_oauth_config
from syncr_api.oauth.injection import build_oauth_state
from syncr_api.oauth.keys import SigningKeySet, generate_signing_key
from syncr_common.logging import configure_logging

# Fixed, so the document is a function of the code alone. `title` is the only one of
# these that reaches the document; the rest exist because `create_app` takes settings.
EXPORT_SETTINGS = ServiceSettings(
    service=API_SERVICE,
    port=API_PORT,
    environment="development",
    log_level="error",
    host="127.0.0.1",
    database_url="postgresql+asyncpg://openapi-export/none",
    session_signing_secret=SecretStr("openapi-export-not-a-session-key"),
    allowed_origins=(),
    public_base_url="https://openapi-export.invalid",
    # Empty, so nothing is read from the filesystem: the export must not depend on a key
    # file existing on the machine that runs it.
    oauth_keys_path="",
    oauth_key_encryption_key=SecretStr("openapi-export-not-an-encryption-key"),
)

# The `kid` is fixed too. No signing key reaches the document, but the state has to exist
# for the OAuth routes to be mountable, and a generated key would be a value that differs
# per run in a script whose whole purpose is to produce the same bytes twice.
EXPORT_KEY_ID = "openapi-export"


def build_document() -> dict[str, object]:
    """Return the OpenAPI document the deployed app serves."""
    configure_logging(environment=EXPORT_SETTINGS.environment, log_level=EXPORT_SETTINGS.log_level)
    app = create_app(EXPORT_SETTINGS)
    # The OAuth routes read their signing keys per request, and the document is produced
    # without serving one, so this exists only so the application is complete rather than
    # half-wired. Nothing derived from it appears in the output.
    oauth_config = build_oauth_config(EXPORT_SETTINGS, is_dev=True)
    app.state.oauth = build_oauth_state(
        oauth_config, SigningKeySet(current=generate_signing_key(EXPORT_KEY_ID))
    )
    return app.openapi()


def render(document: dict[str, object]) -> str:
    """Serialise deterministically, so a regenerated document diffs only on real change."""
    return f"{json.dumps(document, indent=2, sort_keys=True)}\n"


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        sys.stderr.write("usage: export_openapi.py <output-path>\n")
        return 2
    destination = Path(argv[0])
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render(build_document()), encoding="utf-8")
    sys.stdout.write(f"wrote {destination}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
