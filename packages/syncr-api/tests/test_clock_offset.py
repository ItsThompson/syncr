"""The clock offset: one reader, both processes, and refused outside development.

`utc_now` is the only place this package reads the wall clock, so an offset applied there
moves every service that takes the clock as a dependency without any of them being
rewired. That is what makes the seam cheap, and it is also what makes it dangerous, so
three properties are gated here rather than described.

ONE READER. The offset is read in `core/clock.py` and nowhere else. Two readers is how one
shift comes to mean two different things in two processes, and neither reading below is a
list of files: one crosses every tracked Python source against the variable's own name, the
other walks each source's syntax for a read of the environment keyed to it.

BOTH PROCESSES. The api builds its app at import and the worker builds its context, and
each is booted in a child process here, because an in-process check would be asserting
about the suite's own environment rather than about a container's.

REFUSED OUTSIDE DEVELOPMENT, in both directions. A refusal that cannot permit and a permit
that cannot refuse look identical from a green suite, so the refusal is driven at a
production-shaped boot and the permit at a development-shaped one, and the third case is
the one that separates them: a production boot with no offset set has to succeed.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError
from sqlalchemy import text

import syncr_api
from syncr_api.core import clock
from syncr_api.core.clock import CLOCK_OFFSET_ENV_VAR, clock_offset, utc_now
from syncr_api.core.db import create_db_engine
from syncr_api.core.settings import EnvSettings
from syncr_api.oauth.rotation import rotate_signing_keys
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.source_census import (
    INNOCENT_CALL_SPELLINGS,
    SECOND_CLOCK_SPELLINGS,
    SECOND_READER_SPELLINGS,
    api_sources,
    clock_module,
    declared_entrypoints,
    named,
    reads_the_offset,
    reads_the_wall_clock,
    second_reader_source,
    settings_constructors,
    tracked_python_sources,
)
from tests.test_alert_rules import member_roots, repo_root

if TYPE_CHECKING:
    from collections.abc import Mapping

# Long enough that no run of this suite could produce it by drifting, and stated as the
# spelling an operator writes rather than as a number of seconds.
OFFSET = "P3D"
SHIFT = timedelta(days=3)

# Where this suite imported the package from, which is the tree a child is pointed at. A
# child left to itself resolves `syncr_api` through the editable install, which names one
# checkout whichever one the suite is running from.
SOURCE_ROOT = Path(syncr_api.__file__).resolve().parent.parent

# A Fernet key for this probe alone, and not the development default: a production process
# refuses that one whenever a key file exists to encrypt.
PROBE_KEY_ENCRYPTION_KEY = (
    "YS1jbG9jay1wcm9iZS1vYXV0aC1rZXktZW5jcnlwdCE="  # pragma: allowlist secret
)
PROBE_SESSION_SECRET = "a-signing-secret-for-the-clock-probe"  # pragma: allowlist secret


def env(**overrides: object) -> EnvSettings:
    """Settings from explicit values only, so a developer's .env cannot change a test."""
    return EnvSettings(_env_file=None, **overrides)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# What the offset does to this process's clock
# ---------------------------------------------------------------------------


def test_an_unset_variable_leaves_the_clock_where_it_is(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CLOCK_OFFSET_ENV_VAR, raising=False)

    opened = datetime.now(UTC)
    observed = utc_now()
    closed = datetime.now(UTC)

    assert clock_offset() == timedelta(0)
    assert opened <= observed <= closed


def test_the_offset_moves_the_instant_utc_now_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CLOCK_OFFSET_ENV_VAR, OFFSET)

    opened = datetime.now(UTC)
    observed = utc_now()
    closed = datetime.now(UTC)

    assert clock_offset() == SHIFT
    assert opened + SHIFT <= observed <= closed + SHIFT


# Every duration the failure message advertises, mapped to one concrete value and what it
# means. `HH:MM:SS` is a format rather than a value, so its entry is an instance of it. The
# keys are crossed against the message itself below, so adding a spelling to the message
# without teaching this table reddens rather than leaving the message advertising a spelling
# the reader refuses.
ADVERTISED_SPELLINGS = {
    "P3D": ("P3D", timedelta(days=3)),
    "-PT2H": ("-PT2H", timedelta(hours=-2)),
    "PT90M": ("PT90M", timedelta(minutes=90)),
    "HH:MM:SS": ("36:00:00", timedelta(hours=36)),
}


def advertised_spellings(monkeypatch: pytest.MonkeyPatch) -> frozenset[str]:
    """Every duration the failure message offers, read from the message rather than restated."""
    monkeypatch.setenv(CLOCK_OFFSET_ENV_VAR, "a value no reader can read")
    with pytest.raises(ValueError, match=CLOCK_OFFSET_ENV_VAR) as unreadable:
        clock_offset()
    return frozenset(re.findall(r"`([^`]+)`", str(unreadable.value)))


def test_the_message_offers_exactly_the_spellings_this_suite_drives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Without this crossing the parametrization below is a hand-kept list beside the message,
    # and editing the message could not redden the test whose whole point is that the message
    # not advertise a spelling the reader refuses.
    assert advertised_spellings(monkeypatch) == set(ADVERTISED_SPELLINGS)


@pytest.mark.parametrize(
    ("named", "expected"), ADVERTISED_SPELLINGS.values(), ids=list(ADVERTISED_SPELLINGS)
)
def test_the_spellings_the_message_offers_are_the_spellings_it_reads(
    monkeypatch: pytest.MonkeyPatch, named: str, expected: timedelta
) -> None:
    monkeypatch.setenv(CLOCK_OFFSET_ENV_VAR, named)

    assert clock_offset() == expected


@pytest.mark.parametrize("named", ["", "   ", "\t"])
def test_an_empty_value_means_no_offset(monkeypatch: pytest.MonkeyPatch, named: str) -> None:
    # Compose interpolation of an unset variable produces an empty value that overrides the
    # file it would otherwise have come from, so empty has to mean unset rather than fail.
    monkeypatch.setenv(CLOCK_OFFSET_ENV_VAR, named)

    assert clock_offset() == timedelta(0)


def test_a_zero_offset_is_no_offset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CLOCK_OFFSET_ENV_VAR, "PT0S")

    assert clock_offset() == timedelta(0)


@pytest.mark.parametrize("named", ["36h", "129600", "3", "tomorrow", "P", "0"])
def test_a_value_no_reader_can_read_raises_rather_than_meaning_nothing(
    monkeypatch: pytest.MonkeyPatch, named: str
) -> None:
    # A bare number is refused deliberately: `129600` is either seconds or minutes depending
    # on who is reading, and a silent guess is a clock nobody can predict.
    monkeypatch.setenv(CLOCK_OFFSET_ENV_VAR, named)

    with pytest.raises(ValueError, match=CLOCK_OFFSET_ENV_VAR) as unreadable:
        clock_offset()

    assert repr(named) in str(unreadable.value)


# ---------------------------------------------------------------------------
# The refusal outside development
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("environment", ["production", "staging", "test"])
def test_a_shifted_clock_is_refused_anywhere_but_development(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    monkeypatch.setenv(CLOCK_OFFSET_ENV_VAR, OFFSET)

    with pytest.raises(ValidationError, match=CLOCK_OFFSET_ENV_VAR):
        env(environment=environment, session_signing_secret=PROBE_SESSION_SECRET)


def test_the_refusal_names_the_variable_the_shift_and_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This message is the whole user interface of a deployment that inherited the seam, so it
    # says what is set, how far it moves the clock, and which environment refused it.
    monkeypatch.setenv(CLOCK_OFFSET_ENV_VAR, OFFSET)

    with pytest.raises(ValidationError) as refused:
        env(environment="production", session_signing_secret=PROBE_SESSION_SECRET)

    message = str(refused.value)
    assert CLOCK_OFFSET_ENV_VAR in message
    assert str(SHIFT) in message
    assert "production" in message


def test_development_may_shift_its_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CLOCK_OFFSET_ENV_VAR, OFFSET)

    assert env(environment="development").is_dev


@pytest.mark.parametrize("environment", ["production", "staging", "test"])
def test_an_unshifted_deployment_is_not_refused(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    # The half that keeps the refusal from being always-on. Without this the guard could be
    # `raise` and every test above would still pass.
    monkeypatch.delenv(CLOCK_OFFSET_ENV_VAR, raising=False)

    settings = env(environment=environment, session_signing_secret=PROBE_SESSION_SECRET)

    assert not settings.is_dev


@pytest.mark.parametrize("named", ["", "PT0S"])
def test_a_deployment_that_names_no_shift_is_not_refused(
    monkeypatch: pytest.MonkeyPatch, named: str
) -> None:
    # The refusal is keyed on the offset rather than on the variable being present, so the two
    # values that shift nothing are permitted everywhere. Stated as a test because it is the
    # boundary a reader would otherwise have to infer from the condition.
    monkeypatch.setenv(CLOCK_OFFSET_ENV_VAR, named)

    settings = env(environment="production", session_signing_secret=PROBE_SESSION_SECRET)

    assert not settings.is_dev


@pytest.mark.parametrize("environment", ["development", "production"])
def test_an_unreadable_value_fails_the_boot_in_every_environment(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    # Settings construction is the first thing an entrypoint does, so a misspelled duration
    # fails there rather than at whichever request first asked what time it was.
    monkeypatch.setenv(CLOCK_OFFSET_ENV_VAR, "36h")

    with pytest.raises(ValidationError, match=CLOCK_OFFSET_ENV_VAR):
        env(environment=environment, session_signing_secret=PROBE_SESSION_SECRET)


# ---------------------------------------------------------------------------
# One reader, derived from the source
# ---------------------------------------------------------------------------
#
# Two readings, because either alone leaves a hole the other closes. The literal scan catches
# a second module that spells the variable out; the syntax scan catches one that reads the
# environment through this package's own constant, which no literal scan can see. Both live in
# `tests/source_census.py`, which returns data rather than asserting, so each can be driven
# against the real tree and against a deliberately planted second reader.


def test_the_offset_is_spelled_out_in_one_source_file() -> None:
    naming = {
        path
        for path in tracked_python_sources()
        if CLOCK_OFFSET_ENV_VAR in path.read_text(encoding="utf-8")
    }

    assert naming == {clock_module()}


def test_the_environment_is_read_for_the_offset_in_one_source_file() -> None:
    reading = {
        path
        for path in tracked_python_sources()
        if reads_the_offset(ast.parse(path.read_text(encoding="utf-8")))
    }

    assert reading == {clock_module()}


@pytest.mark.parametrize("spelling", SECOND_READER_SPELLINGS)
@pytest.mark.parametrize("alias", [None, "OFFSET_VAR"])
def test_the_reading_finds_a_read_it_is_shown(spelling: str, alias: str | None) -> None:
    # The positive control the census needs, and the reason both readings above can assert an
    # equality safely. A reading that found nothing at all would fail that equality loudly; a
    # reading blind to ONE spelling of a read through the constant would pass it while missing
    # the shape that matters most. Every spelling is crossed against the constant arriving
    # under its own name and under an alias, because an alias hides a read on its own.
    source = second_reader_source(spelling, alias)

    assert reads_the_offset(ast.parse(source)), source


# ---------------------------------------------------------------------------
# What the one reader reaches
# ---------------------------------------------------------------------------


def test_this_package_reads_the_wall_clock_in_one_place() -> None:
    # What makes the offset's reach a fact rather than a claim. A module that read the clock
    # itself would keep the real instant while every dependency-injected reader moved, and
    # nothing else in the suite would notice.
    reading = {
        path
        for path in api_sources()
        if reads_the_wall_clock(ast.parse(path.read_text(encoding="utf-8")))
    }

    assert reading == {clock_module()}


@pytest.mark.parametrize("spelling", SECOND_CLOCK_SPELLINGS)
def test_the_wall_clock_reading_finds_a_read_it_is_shown(spelling: str) -> None:
    # The same control the offset census carries, for the same reason: an equality against one
    # file passes whenever the reading has gone blind, and this guard is what the claim "every
    # reader moves with the offset" rests on.
    assert reads_the_wall_clock(ast.parse(spelling + "\n")), spelling


@pytest.mark.parametrize("innocent", INNOCENT_CALL_SPELLINGS)
def test_the_wall_clock_reading_does_not_read_an_ordinary_call_as_a_clock(innocent: str) -> None:
    # The negative half, and the only thing that catches a reading which widens to everything
    # rather than narrowing: an always-true reading satisfies every case of the control above.
    assert not reads_the_wall_clock(ast.parse(innocent + "\n")), innocent


def test_every_entrypoint_of_this_package_builds_the_settings_that_refuse() -> None:
    # Why the refusal is in `EnvSettings` rather than in the two entrypoints a scenario drives:
    # it then covers every way this package can be started, including the migration one-shot
    # and the console scripts that run inside the backup image. Derived from the build's own
    # script table, so a new entrypoint that skips settings construction reddens here.
    builders = settings_constructors()

    for entrypoint, path in declared_entrypoints().items():
        source = path.read_text(encoding="utf-8")
        called = {
            named(node.func) for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)
        }
        assert called & builders, f"{entrypoint} builds no settings, so nothing refuses there"


def clock_holders() -> tuple[str, ...]:
    """Every module of this package that imports `utc_now`, read from the source."""
    tree = repo_root() / member_roots()[syncr_api.__name__]
    found = []
    for path in api_sources():
        imported = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(imported):
            if not isinstance(node, ast.ImportFrom) or node.module != clock.__name__:
                continue
            if any(alias.name == utc_now.__name__ for alias in node.names):
                dotted = path.relative_to(tree).with_suffix("").parts
                found.append(".".join(dotted).removesuffix(".__init__"))
    return tuple(sorted(set(found)))


def test_every_holder_of_the_clock_holds_the_one_that_moves() -> None:
    holders = clock_holders()

    # The worker declares its runners at import and each takes the clock as an argument, so
    # this module holding a rebound `utc_now` is the shape that would leave the worker on the
    # real clock while the api moved.
    assert "syncr_api.worker.main" in holders
    for holder in holders:
        assert getattr(import_module(holder), utc_now.__name__) is utc_now, holder


# ---------------------------------------------------------------------------
# Both processes
# ---------------------------------------------------------------------------

# What each entrypoint does with the environment when a container starts it. The api builds
# its app at import; the worker builds its context. Both construct `EnvSettings`, which is
# where the refusal lives.
ENTRYPOINT_BOOT = {
    "api": "import syncr_api.api.main",
    "worker": "import syncr_api.worker.main as entrypoint\nentrypoint.build_context()",
}

# Where each entrypoint's process holds the clock. The worker's own module is included
# because it is the reference every runner in its loop was built with.
ENTRYPOINT_READERS = {
    "api": ("syncr_api.core.clock",),
    "worker": ("syncr_api.core.clock", "syncr_api.worker.main"),
}

# The child's report of one instant. Deliberately not a JSON line: the entrypoints emit
# those, and a reading that could not tell the two apart would pass on a log line.
REPORT = "instant"


def clock_probe(entrypoint: str) -> str:
    """A child that boots one entrypoint and reports what each of its clocks says."""
    return "\n".join(
        (
            ENTRYPOINT_BOOT[entrypoint],
            "import importlib",
            f"for name in {ENTRYPOINT_READERS[entrypoint]!r}:",
            f"    print({REPORT!r}, name, importlib.import_module(name).utc_now().isoformat())",
        )
    )


def development_environment(**extra: str) -> dict[str, str]:
    """A curated environment for a child, shaped like the development stack.

    Nothing ambient reaches the child, so the database is named too: creating an engine
    opens no connection, and a closed port is what this process could not reach if it tried.
    """
    return {
        "PATH": "/usr/bin:/bin",
        "ENVIRONMENT": "development",
        "LOG_LEVEL": "info",
        "DATABASE_URL": UNREACHABLE_DATABASE_URL,
        "PYTHONPATH": str(SOURCE_ROOT),
        **extra,
    }


def deployment_environment(*, keys_path: Path, **extra: str) -> dict[str, str]:
    """The same, shaped like a deployment: every secret a production boot refuses to go without."""
    return development_environment(
        ENVIRONMENT="production",
        SESSION_SIGNING_SECRET=PROBE_SESSION_SECRET,
        OAUTH_KEYS_PATH=str(keys_path),
        OAUTH_KEY_ENCRYPTION_KEY=PROBE_KEY_ENCRYPTION_KEY,
        **extra,
    )


def boot(payload: str, environment: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell, no external input
        [sys.executable, "-c", payload],
        capture_output=True,
        text=True,
        check=False,
        env=dict(environment),
    )


def reported(completed: subprocess.CompletedProcess[str]) -> dict[str, datetime]:
    """Every instant the child reported, by the module that reported it."""
    found = {}
    for line in completed.stdout.splitlines():
        if not line.startswith(f"{REPORT} "):
            continue
        _, module, instant = line.split()
        found[module] = datetime.fromisoformat(instant)
    return found


@pytest.mark.parametrize("entrypoint", sorted(ENTRYPOINT_BOOT))
def test_a_booted_process_reports_the_shifted_instant(entrypoint: str) -> None:
    opened = datetime.now(UTC)
    completed = boot(
        clock_probe(entrypoint), development_environment(**{CLOCK_OFFSET_ENV_VAR: OFFSET})
    )
    closed = datetime.now(UTC)

    assert completed.returncode == 0, completed.stderr
    instants = reported(completed)
    assert set(instants) == set(ENTRYPOINT_READERS[entrypoint]), completed.stdout
    for module, instant in instants.items():
        assert opened + SHIFT <= instant <= closed + SHIFT, module


@pytest.mark.parametrize("entrypoint", sorted(ENTRYPOINT_BOOT))
def test_a_booted_process_reports_the_real_instant_with_no_offset_set(entrypoint: str) -> None:
    # The probe's own control. Without it the comparison above would pass against a child
    # whose clock was three days out for some reason of its own.
    opened = datetime.now(UTC)
    completed = boot(clock_probe(entrypoint), development_environment())
    closed = datetime.now(UTC)

    assert completed.returncode == 0, completed.stderr
    instants = reported(completed)
    assert set(instants) == set(ENTRYPOINT_READERS[entrypoint]), completed.stdout
    for module, instant in instants.items():
        assert opened <= instant <= closed, module


@pytest.mark.parametrize("entrypoint", sorted(ENTRYPOINT_BOOT))
def test_a_deployment_shaped_boot_refuses_the_offset(entrypoint: str, tmp_path: Path) -> None:
    # The refusal at the place it has to hold: a process starting the way a container starts
    # it. A validator that ran only when a test constructed settings by hand would pass every
    # check above and let the seam into a deployment.
    keys_path = tmp_path / "oauth-signing-keys.enc"
    rotate_signing_keys(keys_path, PROBE_KEY_ENCRYPTION_KEY)

    completed = boot(
        clock_probe(entrypoint),
        deployment_environment(keys_path=keys_path, **{CLOCK_OFFSET_ENV_VAR: OFFSET}),
    )

    assert completed.returncode != 0, completed.stdout
    assert CLOCK_OFFSET_ENV_VAR in completed.stderr
    assert not reported(completed), "the process reported an instant after refusing to start"


@pytest.mark.parametrize("entrypoint", sorted(ENTRYPOINT_BOOT))
def test_a_deployment_shaped_boot_starts_with_no_offset_set(
    entrypoint: str, tmp_path: Path
) -> None:
    # What makes the refusal above a refusal rather than a boot that never worked. Same
    # environment, same entrypoint, the offset removed.
    keys_path = tmp_path / "oauth-signing-keys.enc"
    rotate_signing_keys(keys_path, PROBE_KEY_ENCRYPTION_KEY)
    opened = datetime.now(UTC)

    completed = boot(clock_probe(entrypoint), deployment_environment(keys_path=keys_path))
    closed = datetime.now(UTC)

    assert completed.returncode == 0, completed.stderr
    instants = reported(completed)
    assert set(instants) == set(ENTRYPOINT_READERS[entrypoint]), completed.stdout
    for module, instant in instants.items():
        assert opened <= instant <= closed, module


# ---------------------------------------------------------------------------
# The clock the offset does not move
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_postgres_keeps_its_own_clock_when_this_process_moves_its(
    live_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The reason this seam is an environment variable read by one Python function rather than
    # a faked clock in the container: `faketime` would lie to Postgres too, and every stored
    # instant would become part of the fiction. A temporary table is used so the reading
    # cannot leave a row or a relation behind for a suite that enumerates them.
    monkeypatch.setenv(CLOCK_OFFSET_ENV_VAR, OFFSET)
    engine = create_db_engine(live_database_url)

    opened = datetime.now(UTC)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("CREATE TEMPORARY TABLE stamped (at timestamptz NOT NULL DEFAULT now())")
            )
            await connection.execute(text("INSERT INTO stamped DEFAULT VALUES"))
            stored = (await connection.execute(text("SELECT at FROM stamped"))).scalar_one()
    finally:
        await engine.dispose()
    shifted = utc_now()
    closed = datetime.now(UTC)

    assert opened <= stored <= closed, "Postgres stamped an instant this process's offset moved"
    assert opened + SHIFT <= shifted <= closed + SHIFT
    assert shifted - stored >= SHIFT
