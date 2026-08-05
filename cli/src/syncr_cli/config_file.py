"""The configuration file, located and read, with every refusal stated where it happens.

Four things go wrong with a configuration file and each is answered differently. There is no
file, which is the ordinary case and not a problem. The file is not TOML, which is a usage error
naming the parse failure and the path. The file names a key this build does not know, which is
refused rather than ignored: a misspelled ``poll_interval`` that silently did nothing is a
setting the user believes they set. The file states a value of the wrong kind, which is refused
by the setting that reads it.

The path is ``$XDG_CONFIG_HOME/syncr/config.toml``, which is ``~/.config/syncr/config.toml`` on
a machine that states no override. The variable is honored rather than the literal path
hard-coded, because that is what the literal path means.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Final

from syncr_cli.errors import UsageError

CONFIG_DIRECTORY_NAME: Final = "syncr"
CONFIG_FILE_NAME: Final = "config.toml"
XDG_CONFIG_HOME: Final = "XDG_CONFIG_HOME"

# Every key the file may carry. A key outside this set is refused, so the message can name what
# is known rather than leaving the user to guess which spelling this build reads.
CONFIG_KEYS: Final = frozenset({"api_url", "poll_interval_ms", "timeout_s", "week", "output"})


def config_path(env: dict[str, str], home: Path) -> Path:
    """Where this machine's configuration file lives."""
    stated = env.get(XDG_CONFIG_HOME, "").strip()
    base = Path(stated) if stated else home / ".config"
    return base / CONFIG_DIRECTORY_NAME / CONFIG_FILE_NAME


def read_config(path: Path) -> dict[str, Any]:
    """The settings the file states, or an empty mapping when there is no file.

    A directory where the file should be, or a file that cannot be read, is reported as itself:
    both are conditions the user can fix, and neither should look like an empty configuration.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}
    except OSError as error:
        raise UsageError(
            f"{path} could not be read: {error.strerror}. Nothing was changed. Fix the file or "
            "remove it; every setting can also be given as a flag or a SYNCR_ variable."
        ) from error
    return _parse(raw, path)


def _parse(raw: bytes, path: Path) -> dict[str, Any]:
    try:
        parsed = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
        raise UsageError(
            f"{path} is not readable as TOML: {error}. Nothing was changed. Every setting can "
            "also be given as a flag or a SYNCR_ variable."
        ) from error
    unknown = sorted(set(parsed) - CONFIG_KEYS)
    if unknown:
        known = ", ".join(sorted(CONFIG_KEYS))
        raise UsageError(
            f"{path} states {_and_joined(unknown)}, which this CLI does not read. It reads: "
            f"{known}. A key it ignored would be a setting you believe you set."
        )
    return parsed


def _and_joined(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"


def default_home() -> Path:
    """This machine's home directory, read once so a caller can substitute one."""
    return Path(os.path.expanduser("~"))
