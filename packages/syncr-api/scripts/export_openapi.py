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
)


def build_document() -> dict[str, object]:
    """Return the OpenAPI document the deployed app serves."""
    configure_logging(environment=EXPORT_SETTINGS.environment, log_level=EXPORT_SETTINGS.log_level)
    return create_app(EXPORT_SETTINGS).openapi()


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
