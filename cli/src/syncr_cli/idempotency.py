"""The ``Idempotency-Key`` a mutating command sends, derived rather than invented.

An agent retrying a ``POST`` must not create a second pin or a second task, so every mutation
carries a key. Deriving it from the command and its arguments means a retry of the same
invocation carries the same key without the caller having to remember one, and a genuinely
different invocation carries a different key.

**Derivation is deterministic and states its inputs.** The command path and the arguments, both
normalized, hashed once. Two invocations with identical arguments derive the same key on any
machine, in any order of flags, at any time: no clock, no random source, no process id.

**A key is 200 characters at most**, which the api's column enforces. A digest is 64 and the
prefix is 11, so the derived form cannot approach it; a key supplied with ``--idempotency-key``
is checked against the same bound here, where the message can say what the limit is.
"""

from __future__ import annotations

import hashlib
import json
from typing import Final

from syncr_cli.errors import UsageError

IDEMPOTENCY_KEY_HEADER: Final = "Idempotency-Key"

# The bound the api's column states. Checked here so a caller learns the limit from the client
# rather than from a 400 after the request went out.
KEY_MAX_LENGTH: Final = 200

# What a derived key looks like, so an operator reading a row can tell one this CLI derived from
# one a caller supplied.
DERIVED_KEY_PREFIX: Final = "syncr-cli-"


def derive_key(command: tuple[str, ...], arguments: dict[str, object]) -> str:
    """The key for one invocation of one command.

    The arguments are serialized with sorted keys and no whitespace, so the derivation cannot
    depend on the order the parser happened to fill them in. ``None`` members are dropped rather
    than serialized: an argument the user did not state and an argument they stated as null are
    the same request, and carrying the distinction would give one request two keys.
    """
    stated = {name: value for name, value in sorted(arguments.items()) if value is not None}
    canonical = json.dumps(
        {"command": list(command), "arguments": stated},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{DERIVED_KEY_PREFIX}{digest}"


def supplied_key(key: str) -> str:
    """A caller's own key, checked against the bound the api will apply."""
    stated = key.strip()
    if not stated:
        raise UsageError(
            "--idempotency-key carries no value. Nothing was changed. Omit the flag to have one "
            "derived from the command and its arguments."
        )
    if len(stated) > KEY_MAX_LENGTH:
        raise UsageError(
            f"--idempotency-key is {len(stated)} characters, and the API accepts at most "
            f"{KEY_MAX_LENGTH}. Nothing was changed."
        )
    return stated
