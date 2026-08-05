"""The configuration file: absent, malformed, unreadable, and stating a key nobody reads.

Four conditions, four different answers. Absent is the ordinary case and not a problem. The other
three are usage errors that name the path, because a file the user can fix is only fixable if they
are told which file it is.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syncr_cli.config_file import CONFIG_KEYS, config_path, read_config
from syncr_cli.errors import UsageError

if TYPE_CHECKING:
    from pathlib import Path


def test_the_path_is_under_the_home_directory_by_default(tmp_path: Path) -> None:
    assert config_path({}, tmp_path) == tmp_path / ".config" / "syncr" / "config.toml"


def test_the_xdg_variable_is_honored_because_that_is_what_the_path_means(tmp_path: Path) -> None:
    stated = tmp_path / "elsewhere"

    assert config_path({"XDG_CONFIG_HOME": str(stated)}, tmp_path) == (
        stated / "syncr" / "config.toml"
    )


def test_an_empty_xdg_variable_falls_back_rather_than_rooting_the_path(tmp_path: Path) -> None:
    assert config_path({"XDG_CONFIG_HOME": "  "}, tmp_path).is_relative_to(tmp_path)


def test_no_file_is_not_a_problem(tmp_path: Path) -> None:
    assert read_config(tmp_path / "nothing.toml") == {}


def test_a_file_is_read_as_its_settings(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('api_url = "https://syncr.example"\npoll_interval_ms = 250\n', encoding="utf-8")

    assert read_config(path) == {"api_url": "https://syncr.example", "poll_interval_ms": 250}


def test_a_file_that_is_not_toml_names_the_file_and_the_failure(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("api_url = \n", encoding="utf-8")

    with pytest.raises(UsageError, match=str(path)):
        read_config(path)


def test_a_key_this_build_does_not_read_is_refused_and_the_known_ones_are_named(
    tmp_path: Path,
) -> None:
    # The misspelling that matters: `poll_interval` silently ignored is a setting the user
    # believes they set, and a poll they think is 50ms is one they will not investigate.
    path = tmp_path / "config.toml"
    path.write_text("poll_interval = 50\n", encoding="utf-8")

    with pytest.raises(UsageError) as refused:
        read_config(path)

    assert "poll_interval" in str(refused.value)
    for known in CONFIG_KEYS:
        assert known in str(refused.value)


def test_a_directory_where_the_file_should_be_is_reported_rather_than_read_as_empty(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"
    path.mkdir()

    with pytest.raises(UsageError, match=str(path)):
        read_config(path)


def test_a_file_that_is_not_utf8_is_reported_rather_than_faulting(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes(b"\xff\xfe api_url = 'x'")

    with pytest.raises(UsageError, match="not readable as TOML"):
        read_config(path)
