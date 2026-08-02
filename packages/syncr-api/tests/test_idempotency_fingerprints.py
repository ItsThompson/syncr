"""The request hash and the lock token: the two derived values the guard is built on."""

from __future__ import annotations

from uuid import uuid4

from syncr_api.idempotency.fingerprints import lock_token, request_fingerprint

SIGNED_64_BIT_MIN = -(2**63)
SIGNED_64_BIT_MAX = 2**63 - 1


def test_the_same_bytes_hash_the_same() -> None:
    body = b'{"minutes": 45}'

    assert request_fingerprint(body) == request_fingerprint(bytes(body))


def test_a_body_that_differs_at_all_hashes_differently() -> None:
    # Taken over the raw bytes, before parsing, on purpose. Two bodies that differ only in
    # whitespace are two requests as far as this is concerned, which answers 422 and asks for a
    # new key. The other direction would replay the wrong response.
    assert request_fingerprint(b'{"minutes": 45}') != request_fingerprint(b'{"minutes":45}')
    assert request_fingerprint(b'{"minutes": 45}') != request_fingerprint(b'{"minutes": 46}')


def test_an_empty_body_still_hashes() -> None:
    # A POST with no body is a real request: a re-solve control sends one.
    assert len(request_fingerprint(b"")) == 64


def test_a_token_fits_a_signed_sixty_four_bit_integer() -> None:
    # What Postgres advisory locks take. A value outside the range would raise at the lock
    # rather than answer the request.
    token = lock_token(uuid4(), "/api/v1/pins", "9f3c" * 8)

    assert SIGNED_64_BIT_MIN <= token <= SIGNED_64_BIT_MAX


def test_the_token_separates_the_tenant_the_route_and_the_key() -> None:
    tenant, other_tenant = uuid4(), uuid4()
    route, key = "/api/v1/pins", "abc"

    assert lock_token(tenant, route, key) == lock_token(tenant, route, key)
    assert lock_token(tenant, route, key) != lock_token(other_tenant, route, key)
    assert lock_token(tenant, route, key) != lock_token(tenant, "/api/v1/tasks", key)
    assert lock_token(tenant, route, key) != lock_token(tenant, route, "abd")


def test_the_parts_cannot_be_shifted_between_each_other() -> None:
    # A token built by concatenating without a separator would give one number for a route
    # ending in a character the key begins with, and two different keys would share a lock.
    tenant = uuid4()

    assert lock_token(tenant, "/api/v1/pin", "sabc") != lock_token(tenant, "/api/v1/pins", "abc")
