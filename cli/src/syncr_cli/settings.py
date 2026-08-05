"""The five settings, and the four places each may come from.

Precedence runs: the command flag, then a ``SYNCR_`` environment variable, then the
configuration file, then the built-in default. One resolver, so no command can read a setting
in a different order from another.

**The default output format is the one that matters most for an agent.** Human when stdout is a
terminal and JSON otherwise, so piping this CLI anywhere produces machine-readable output with
no flag. That removes an entire class of "the agent forgot ``--json``" failure.

**``api_url``'s built-in default is the development host, not a deployment's.** The deployed
hostname is per-deployment configuration that lives nowhere in this repository, so naming one
here would be a claim about an installation this build cannot know. A deployment states it in
``SYNCR_API_URL`` or in the configuration file.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

from syncr_cli.errors import UsageError
from syncr_domain.weeks import IsoWeek, IsoWeekError

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date


class OutputFormat(StrEnum):
    """How a command writes its result. Two formats, from one result object."""

    HUMAN = "human"
    JSON = "json"


ENV_PREFIX: Final = "SYNCR_"

DEFAULT_API_URL: Final = "http://localhost:8000"
DEFAULT_POLL_INTERVAL_MS: Final = 500
DEFAULT_TIMEOUT_S: Final = 60

# A poll interval and a timeout are both bounded below by one, not by zero: a zero interval is a
# tight loop against the API, and a zero timeout is a wait that cannot observe anything.
MINIMUM_POLL_INTERVAL_MS: Final = 1
MINIMUM_TIMEOUT_S: Final = 1


@dataclass(frozen=True, slots=True)
class Flags:
    """What the command line stated. Every member is absent unless the user wrote it."""

    api_url: str | None = None
    poll_interval_ms: int | None = None
    timeout_s: int | None = None
    week: str | None = None
    output: str | None = None


@dataclass(frozen=True, slots=True)
class Settings:
    """The resolved configuration one invocation runs against."""

    api_url: str
    poll_interval_ms: int
    timeout_s: int
    week: IsoWeek
    output: OutputFormat


def resolve_settings(
    *,
    flags: Flags,
    env: Mapping[str, str],
    config: Mapping[str, Any],
    stdout_is_tty: bool,
    today: date,
) -> Settings:
    """The settings this invocation runs against, resolved once at startup."""
    return Settings(
        api_url=_api_url(flags, env, config),
        poll_interval_ms=_bounded_number(
            "poll_interval_ms",
            flags.poll_interval_ms,
            env,
            config,
            default=DEFAULT_POLL_INTERVAL_MS,
            minimum=MINIMUM_POLL_INTERVAL_MS,
        ),
        timeout_s=_bounded_number(
            "timeout_s",
            flags.timeout_s,
            env,
            config,
            default=DEFAULT_TIMEOUT_S,
            minimum=MINIMUM_TIMEOUT_S,
        ),
        week=_week(flags, env, config, today),
        output=_output(flags, env, config, stdout_is_tty=stdout_is_tty),
    )


def environment_variable(setting: str) -> str:
    """The variable name a setting is read from, so the name is derived rather than restated."""
    return f"{ENV_PREFIX}{setting.upper()}"


def _api_url(flags: Flags, env: Mapping[str, str], config: Mapping[str, Any]) -> str:
    stated = _stated("api_url", flags.api_url, env, config)
    if stated is None:
        return DEFAULT_API_URL
    url = _as_text("api_url", stated).rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise UsageError(
            f"{_source('api_url')} is {url!r}, which is not an http or https URL. Nothing was "
            "changed."
        )
    return url


def _bounded_number(
    setting: str,
    flag: int | None,
    env: Mapping[str, str],
    config: Mapping[str, Any],
    *,
    default: int,
    minimum: int,
) -> int:
    stated = _stated(setting, flag, env, config)
    if stated is None:
        return default
    number = _as_number(setting, stated)
    if number < minimum:
        raise UsageError(
            f"{_source(setting)} is {number}, and the smallest usable value is {minimum}. "
            "Nothing was changed."
        )
    return number


def _week(flags: Flags, env: Mapping[str, str], config: Mapping[str, Any], today: date) -> IsoWeek:
    stated = _stated("week", flags.week, env, config)
    if stated is None:
        # The machine's current ISO week, which is a local-date question: a machine in a zone
        # ahead of the server's is in the next week for part of a day, and at a year boundary in
        # the next ISO year. `--week` is how that is stated rather than inferred.
        return IsoWeek.containing(today)
    raw = _as_text("week", stated)
    try:
        return IsoWeek.parse(raw)
    except IsoWeekError as error:
        raise UsageError(
            f"{_source('week')} is {raw!r}, which names no ISO week. Weeks are written "
            "'2026-W07', and week 53 exists only in a long year."
        ) from error


def _output(
    flags: Flags, env: Mapping[str, str], config: Mapping[str, Any], *, stdout_is_tty: bool
) -> OutputFormat:
    stated = _stated("output", flags.output, env, config)
    if stated is None:
        return OutputFormat.HUMAN if stdout_is_tty else OutputFormat.JSON
    raw = _as_text("output", stated)
    try:
        return OutputFormat(raw)
    except ValueError as error:
        named = ", ".join(member.value for member in OutputFormat)
        raise UsageError(
            f"{_source('output')} is {raw!r}, and the formats are: {named}. Nothing was changed."
        ) from error


def _stated(
    setting: str, flag: object | None, env: Mapping[str, str], config: Mapping[str, Any]
) -> object | None:
    """The highest-precedence statement of ``setting``, or ``None`` when nothing states it.

    An empty environment variable is treated as unstated. ``SYNCR_WEEK=`` in a shell profile is
    a variable someone meant to clear, and reading it as a value would refuse every command.
    """
    if flag is not None:
        return flag
    from_env = env.get(environment_variable(setting))
    if from_env is not None and from_env.strip():
        return from_env.strip()
    return config.get(setting)


def _source(setting: str) -> str:
    """How a refusal names the setting, covering all three places it could have come from."""
    return f"{setting} (a flag, {environment_variable(setting)}, or the configuration file)"


def _as_text(setting: str, value: object) -> str:
    if not isinstance(value, str):
        raise UsageError(
            f"{_source(setting)} is {value!r}, and this setting is text. Nothing was changed."
        )
    return value.strip()


def _as_number(setting: str, value: object) -> int:
    """A whole number, from a flag, a string variable, or a TOML integer.

    ``bool`` is refused before ``int`` because it is an ``int`` subclass, so ``true`` in the
    configuration file would otherwise read as one.
    """
    if isinstance(value, bool):
        raise UsageError(
            f"{_source(setting)} is {value!r}, and this setting is a whole number of "
            f"{'milliseconds' if setting.endswith('_ms') else 'seconds'}. Nothing was changed."
        )
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as error:
            raise UsageError(
                f"{_source(setting)} is {value!r}, which is not a whole number. Nothing was "
                "changed."
            ) from error
    raise UsageError(
        f"{_source(setting)} is {value!r}, and this setting is a whole number. Nothing was changed."
    )
