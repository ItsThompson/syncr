"""The suite's own logging configuration, and the entrypoints' ownership of it.

`create_app` deliberately does not configure logging: it is a process-global side
effect and an entrypoint owns it. That makes two things worth gating rather than
documenting. The suite must actually run with the strict event-name check on, which it
silently stopped doing once one test reconfigured to `production` and never restored.
And each entrypoint must actually call `configure_logging`, because two more
entrypoints (the CLI and the nightly job) are coming and the failure mode is
console-rendered lines in production.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from syncr_api.oauth.rotation import rotate_signing_keys
from syncr_common.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

# A Fernet key for this probe alone, and not the development default: a production process
# refuses that one whenever a key file exists to encrypt.
_PROBE_KEY_ENCRYPTION_KEY = (
    "YS1wcm9iZS1vbmx5LW9hdXRoLWtleS1lbmNyeXB0aW8="  # pragma: allowlist secret
)

# Importing the api entrypoint is what a container does: the module configures logging
# and then builds the app at import, so one JSON line on stdout is the whole assertion.
# A subprocess is the only honest way to check it, because the suite configures logging
# itself and an in-process check would pass on the suite's configuration instead.
_ENTRYPOINT_PROBE = "import syncr_api.api.main"


def test_the_suite_enforces_the_strict_event_name_check() -> None:
    # The conftest fixture claims `test` mode turns this on. Gate the claim: when it
    # regressed, every module collected after `test_correlation.py` ran without it.
    with pytest.raises(ValueError, match="dotted stable name"):
        get_logger("syncr-api-test").info("solve finished successfully")


def test_a_dotted_event_name_is_accepted() -> None:
    # The negative above would also pass if every event name raised.
    get_logger("syncr-api-test").info("api.suite.probe", iso_week="2026-W07")


def test_the_api_entrypoint_configures_logging(tmp_path: Path) -> None:
    # A production process supplies every secret a deployment supplies, and refuses to be
    # built without them: the session signing secret, and an OAuth signing key file it can
    # read. The key file is created here by the rotation command, which is what a deployment
    # runs, so this also proves a production-shaped boot reads a real encrypted key set.
    keys_path = tmp_path / "oauth-signing-keys.enc"
    rotate_signing_keys(keys_path, _PROBE_KEY_ENCRYPTION_KEY)
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, no external input
        [sys.executable, "-c", _ENTRYPOINT_PROBE],
        capture_output=True,
        text=True,
        check=True,
        env={
            "PATH": "/usr/bin:/bin",
            "ENVIRONMENT": "production",
            "LOG_LEVEL": "info",
            # A production process refuses to be built with the development session
            # signing secret, so the probe supplies one exactly as a deployment does.
            "SESSION_SIGNING_SECRET": "a-signing-secret-for-this-probe",  # pragma: allowlist secret
            "OAUTH_KEYS_PATH": str(keys_path),
            "OAUTH_KEY_ENCRYPTION_KEY": _PROBE_KEY_ENCRYPTION_KEY,
        },
    )

    lines = [json.loads(line) for line in completed.stdout.splitlines() if line.startswith("{")]
    assert lines, (
        "the entrypoint emitted no JSON line, so it did not configure logging: "
        f"{completed.stdout!r}"
    )
    assert lines[0]["event"] == "api.app.configured"
    assert lines[0]["service"] == "syncr-api"
