"""Password hashing for the one account a P0 deployment holds.

``hashlib.scrypt`` rather than a new dependency: it is memory-hard, it is OpenSSL's
implementation rather than one written here, and it keeps the api image and the
audited dependency graph unchanged. The only thing written here is the encoding, and
it carries the parameters it was produced with, so raising the cost later verifies
every existing hash while re-hashing nothing.

Cost is chosen against the container's memory limit rather than against a benchmark.
``n=2**15, r=8`` needs about 34 MB and 120 ms per attempt. Sign-in is unauthenticated
and unthrottled, so each concurrent attempt is a real allocation inside a 768 MB
budget the api already spends 400 MB of; a parameter set four times heavier would
turn a handful of simultaneous attempts into an out-of-memory kill. Cloudflare fronts
the only ingress, so request-rate limiting belongs there rather than in a per-attempt
memory cost this process pays.

That 120 ms is CPU held, not time waited, so an async caller must NOT call the plain
functions: a derivation on the event loop stalls every other in-flight request on the
same worker for its whole duration, which turns an unthrottled endpoint from slow into
an availability problem for the rest of the API. :func:`hash_password_in_thread` and
:func:`verify_password_in_thread` are what an ``async def`` calls. OpenSSL releases the
GIL during the derivation, so a thread genuinely runs it in parallel, and each thread
still allocates its own 34 MB, so the memory reasoning above is unchanged.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
from base64 import urlsafe_b64decode, urlsafe_b64encode

ALGORITHM = "scrypt"

SCRYPT_COST = 2**15
SCRYPT_BLOCK_SIZE = 8
SCRYPT_PARALLELISM = 1
SALT_BYTES = 16
DERIVED_KEY_BYTES = 32

# scrypt needs 128 * n * r bytes and OpenSSL refuses to exceed `maxmem`, whose
# default (32 MB) is below what the cost above requires. Doubled so a parameter bump
# does not have to remember to move this too.
SCRYPT_MAX_MEMORY = 2 * 128 * SCRYPT_COST * SCRYPT_BLOCK_SIZE

_FIELD_SEPARATOR = "$"
_FIELD_COUNT = 6

# A verification against a nonexistent user derives against this, discards the
# result, and returns False. Sign-in must cost the same whether the email exists or
# not, or the response time answers the question the response body deliberately does
# not. The salt is fixed because nothing is stored or compared: the derivation exists
# only to spend the same time the real path spends.
_ABSENT_USER_SALT = bytes(SALT_BYTES)


def hash_password(password: str) -> str:
    """Derive a stored password hash, salted and self-describing."""
    salt = secrets.token_bytes(SALT_BYTES)
    derived = _derive(password, salt, SCRYPT_COST, SCRYPT_BLOCK_SIZE, SCRYPT_PARALLELISM)
    return _encode(salt, derived)


def verify_password(password: str, encoded: str | None) -> bool:
    """True when ``password`` produced ``encoded``.

    ``encoded`` is ``None`` when no user matched, and a derivation still runs before
    False is returned, so the caller cannot accidentally turn "no such account" into a
    faster answer than "wrong password". A stored value this function cannot parse
    verifies as False rather than raising: a row that cannot be read must not
    authenticate anyone, and it must not answer 500 either.
    """
    if encoded is None:
        _derive(password, _ABSENT_USER_SALT, SCRYPT_COST, SCRYPT_BLOCK_SIZE, SCRYPT_PARALLELISM)
        return False
    parsed = _decode(encoded)
    if parsed is None:
        return False
    salt, expected, cost, block_size, parallelism = parsed
    actual = _derive(password, salt, cost, block_size, parallelism)
    return hmac.compare_digest(actual, expected)


async def hash_password_in_thread(password: str) -> str:
    """:func:`hash_password`, off the event loop. What an ``async def`` calls."""
    return await asyncio.to_thread(hash_password, password)


async def verify_password_in_thread(password: str, encoded: str | None) -> bool:
    """:func:`verify_password`, off the event loop. What an ``async def`` calls."""
    return await asyncio.to_thread(verify_password, password, encoded)


def _derive(password: str, salt: bytes, cost: int, block_size: int, parallelism: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=cost,
        r=block_size,
        p=parallelism,
        maxmem=2 * 128 * cost * block_size,
        dklen=DERIVED_KEY_BYTES,
    )


def _encode(salt: bytes, derived: bytes) -> str:
    return _FIELD_SEPARATOR.join(
        (
            ALGORITHM,
            str(SCRYPT_COST),
            str(SCRYPT_BLOCK_SIZE),
            str(SCRYPT_PARALLELISM),
            _b64(salt),
            _b64(derived),
        )
    )


def _decode(encoded: str) -> tuple[bytes, bytes, int, int, int] | None:
    """``(salt, derived, cost, block_size, parallelism)``, or ``None`` if unreadable."""
    fields = encoded.split(_FIELD_SEPARATOR)
    if len(fields) != _FIELD_COUNT or fields[0] != ALGORITHM:
        return None
    algorithm_cost, block_size, parallelism, salt, derived = fields[1:]
    try:
        return (
            _unb64(salt),
            _unb64(derived),
            int(algorithm_cost),
            int(block_size),
            int(parallelism),
        )
    except ValueError:
        return None


def _b64(raw: bytes) -> str:
    return urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(encoded: str) -> bytes:
    padding = "=" * (-len(encoded) % 4)
    return urlsafe_b64decode(encoded + padding)
