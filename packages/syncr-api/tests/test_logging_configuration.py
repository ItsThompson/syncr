"""The suite's own logging configuration, and the entrypoints' ownership of it.

`create_app` deliberately does not configure logging: it is a process-global side
effect and an entrypoint owns it. That makes two things worth gating rather than
documenting. The suite must actually run with the strict event-name check on, which it
silently stopped doing once one test reconfigured to `production` and never restored.
And each entrypoint must actually call `configure_logging`, because two more
entrypoints (the CLI and the nightly job) are coming and the failure mode is
console-rendered lines in production.

The second gate reads a child process, so the probe also states which tree that child
imports and reports the one it resolved. Its environment is curated rather than
inherited, so it carries no `PYTHONPATH` of the parent's, and without one the child
resolves `syncr_api` through the interpreter's editable install: that names a single
checkout whichever checkout the suite is running from.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import syncr_api
from syncr_api.oauth.rotation import rotate_signing_keys
from syncr_common.logging import get_logger

# A Fernet key for this probe alone, and not the development default: a production process
# refuses that one whenever a key file exists to encrypt.
_PROBE_KEY_ENCRYPTION_KEY = (
    "YS1wcm9iZS1vbmx5LW9hdXRoLWtleS1lbmNyeXB0aW8="  # pragma: allowlist secret
)

# Where this suite's own interpreter imported the package from. Children are pointed here
# unless a caller states another root.
_SOURCE_ROOT = Path(syncr_api.__file__).resolve().parent.parent

# The child's report of the tree it imported. Deliberately not a JSON line: the assertion
# that the entrypoint emitted one has to keep failing when the entrypoint emits none.
_ROOT_REPORT = "source-root"

# Importing the api entrypoint is what a container does: the module configures logging
# and then builds the app at import, so a JSON line on stdout is what says it did.
# A subprocess is the only honest way to check it, because the suite configures logging
# itself and an in-process check would pass on the suite's configuration instead. The
# import comes first, so the app's own line is still the first JSON line on stdout.
_ENTRYPOINT_PROBE = (
    "import syncr_api.api.main;"
    "import pathlib, syncr_api;"
    f"print({_ROOT_REPORT!r}, pathlib.Path(syncr_api.__file__).resolve().parent.parent)"
)


def _boot_the_entrypoint(*, source_root: Path, keys_path: Path) -> subprocess.CompletedProcess[str]:
    """Import the api entrypoint in a production-shaped process reading `source_root`."""
    return subprocess.run(  # noqa: S603 - fixed argv, no shell, no external input
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
            # Which tree the child imports. Nothing else of the ambient environment reaches
            # it, this one included, so a suite running anywhere but the checkout the
            # editable install names would assert about a tree nobody is editing.
            "PYTHONPATH": str(source_root),
        },
    )


def _reported_root(stdout: str) -> Path:
    """The source root the child says it imported."""
    reported = [line for line in stdout.splitlines() if line.startswith(_ROOT_REPORT)]

    assert len(reported) == 1, f"the probe reported no source root: {stdout!r}"
    return Path(reported[0].removeprefix(_ROOT_REPORT).strip())


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

    completed = _boot_the_entrypoint(source_root=_SOURCE_ROOT, keys_path=keys_path)

    # The instrument's own precondition. A child that resolved the package elsewhere reports a
    # production boot of a checkout nobody is editing.
    booted = _reported_root(completed.stdout)
    assert booted == _SOURCE_ROOT, f"the probe booted {booted}, this suite imported {_SOURCE_ROOT}"

    lines = [json.loads(line) for line in completed.stdout.splitlines() if line.startswith("{")]
    assert lines, (
        "the entrypoint emitted no JSON line, so it did not configure logging: "
        f"{completed.stdout!r}"
    )
    assert lines[0]["event"] == "api.app.configured"
    assert lines[0]["service"] == "syncr-api"


def test_the_probe_boots_the_tree_it_is_pointed_at(tmp_path: Path) -> None:
    # What the comparison above compares is only worth anything if the stated root is what
    # decides the child's tree. Here the two candidates differ: a stub tree the editable install
    # cannot supply, against the checkout it names. Unlike the comparison above, that holds in a
    # single checkout, so this is the half of the instruction CI can see.
    stub_root = tmp_path / "stub"
    (stub_root / "syncr_api" / "api").mkdir(parents=True)
    for module in ("syncr_api/__init__.py", "syncr_api/api/__init__.py", "syncr_api/api/main.py"):
        (stub_root / module).write_text('"""a tree nobody chose."""\n', encoding="utf-8")
    keys_path = tmp_path / "oauth-signing-keys.enc"
    rotate_signing_keys(keys_path, _PROBE_KEY_ENCRYPTION_KEY)

    completed = _boot_the_entrypoint(source_root=stub_root, keys_path=keys_path)

    booted = _reported_root(completed.stdout)
    assert booted == stub_root, f"the probe booted {booted}, this test pointed it at {stub_root}"
