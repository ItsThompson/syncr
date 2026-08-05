"""Configuration precedence, and every boundary a setting has.

The precedence is one rule for five settings, so it is asserted per source and then per setting:
the flag beats the variable, the variable beats the file, and the file beats the default. What
makes this worth asserting exhaustively is that a silently ignored setting is a setting the user
believes they set.
"""

from __future__ import annotations

from datetime import date

import pytest

from syncr_cli.errors import UsageError
from syncr_cli.settings import (
    DEFAULT_API_URL,
    DEFAULT_POLL_INTERVAL_MS,
    DEFAULT_TIMEOUT_S,
    Flags,
    OutputFormat,
    Settings,
    environment_variable,
    resolve_settings,
)

# A Tuesday in the middle of an ordinary ISO week.
MIDWEEK = date(2026, 2, 10)


def resolve(
    *,
    flags: Flags | None = None,
    env: dict[str, str] | None = None,
    config: dict[str, object] | None = None,
    stdout_is_tty: bool = True,
    today: date = MIDWEEK,
) -> Settings:
    return resolve_settings(
        flags=flags or Flags(),
        env=env or {},
        config=config or {},
        stdout_is_tty=stdout_is_tty,
        today=today,
    )


def test_nothing_stated_gives_the_built_in_defaults() -> None:
    settings = resolve()

    assert settings.api_url == DEFAULT_API_URL
    assert settings.poll_interval_ms == DEFAULT_POLL_INTERVAL_MS
    assert settings.timeout_s == DEFAULT_TIMEOUT_S
    assert str(settings.week) == "2026-W07"


def test_the_file_beats_the_default() -> None:
    assert resolve(config={"api_url": "https://from-file"}).api_url == "https://from-file"


def test_the_variable_beats_the_file() -> None:
    settings = resolve(
        env={environment_variable("api_url"): "https://from-env"},
        config={"api_url": "https://from-file"},
    )

    assert settings.api_url == "https://from-env"


def test_the_flag_beats_the_variable() -> None:
    settings = resolve(
        flags=Flags(api_url="https://from-flag"),
        env={environment_variable("api_url"): "https://from-env"},
        config={"api_url": "https://from-file"},
    )

    assert settings.api_url == "https://from-flag"


@pytest.mark.parametrize(
    ("setting", "stated", "read"),
    [
        ("poll_interval_ms", "250", 250),
        ("timeout_s", "5", 5),
    ],
)
def test_a_number_arrives_as_text_from_a_variable(setting: str, stated: str, read: int) -> None:
    settings = resolve(env={environment_variable(setting): stated})

    assert getattr(settings, setting) == read


def test_an_empty_variable_is_treated_as_unstated() -> None:
    # A `SYNCR_WEEK=` left in a shell profile is a variable someone meant to clear. Reading it as a
    # value would refuse every command on that machine.
    settings = resolve(env={environment_variable("week"): "   "}, config={"week": "2026-W02"})

    assert str(settings.week) == "2026-W02"


def test_a_trailing_slash_on_the_api_url_is_dropped_so_one_path_is_built_one_way() -> None:
    assert resolve(flags=Flags(api_url="https://syncr.example/")).api_url == "https://syncr.example"


def test_output_defaults_to_human_on_a_terminal() -> None:
    assert resolve(stdout_is_tty=True).output is OutputFormat.HUMAN


def test_output_defaults_to_json_when_stdout_is_not_a_terminal() -> None:
    # The default that matters most for an agent: piping this CLI anywhere is machine-readable
    # with no flag, which removes an entire class of "the agent forgot --json" failure.
    assert resolve(stdout_is_tty=False).output is OutputFormat.JSON


def test_a_stated_format_beats_the_terminal_test_in_both_directions() -> None:
    assert resolve(flags=Flags(output="json"), stdout_is_tty=True).output is OutputFormat.JSON
    assert resolve(flags=Flags(output="human"), stdout_is_tty=False).output is OutputFormat.HUMAN


def test_the_default_week_is_the_iso_week_rather_than_the_calendar_one() -> None:
    # 1 January 2027 belongs to ISO week 53 of 2026, which is the case a derivation from the
    # calendar year gets wrong by a whole year.
    assert str(resolve(today=date(2027, 1, 1)).week) == "2026-W53"


def test_a_january_first_that_is_a_monday_is_week_one_of_its_own_year() -> None:
    assert str(resolve(today=date(2029, 1, 1)).week) == "2029-W01"


def test_the_fifty_third_week_of_a_long_year_resolves_to_week_53() -> None:
    assert str(resolve(today=date(2026, 12, 28)).week) == "2026-W53"


@pytest.mark.parametrize("stated", ["2026-W54", "2027-W53", "week 7", "2026W07", ""])
def test_a_week_that_names_no_iso_week_is_a_usage_error(stated: str) -> None:
    with pytest.raises(UsageError, match="ISO week"):
        resolve(flags=Flags(week=stated))


@pytest.mark.parametrize("stated", ["localhost:8000", "ftp://syncr.example", "syncr.example"])
def test_an_api_url_without_a_scheme_is_refused(stated: str) -> None:
    with pytest.raises(UsageError, match="http or https"):
        resolve(flags=Flags(api_url=stated))


@pytest.mark.parametrize("setting", ["poll_interval_ms", "timeout_s"])
def test_a_number_below_its_floor_is_refused(setting: str) -> None:
    # A zero poll interval is a tight loop against the API and a zero timeout observes nothing.
    with pytest.raises(UsageError, match="smallest usable value"):
        resolve(config={setting: 0})


@pytest.mark.parametrize("setting", ["poll_interval_ms", "timeout_s"])
def test_a_number_stated_as_a_boolean_is_refused(setting: str) -> None:
    # `true` in TOML is a bool, and bool is an int subclass in Python, so an unguarded reader
    # would take it as one millisecond.
    with pytest.raises(UsageError, match="whole number"):
        resolve(config={setting: True})


def test_a_number_that_is_not_a_number_is_refused_by_name() -> None:
    with pytest.raises(UsageError, match=environment_variable("timeout_s")):
        resolve(env={environment_variable("timeout_s"): "soon"})


def test_a_setting_that_should_be_text_and_is_not_is_refused() -> None:
    with pytest.raises(UsageError, match="this setting is text"):
        resolve(config={"api_url": 8000})


def test_an_unknown_output_format_names_the_formats_that_exist() -> None:
    with pytest.raises(UsageError, match="human, json"):
        resolve(flags=Flags(output="yaml"))
