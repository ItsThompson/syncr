"""The request hash and the lock token: the two derived values the guard is built on."""

from __future__ import annotations

from uuid import uuid4

from syncr_api.idempotency.fingerprints import lock_token, request_fingerprint

SIGNED_64_BIT_MIN = -(2**63)
SIGNED_64_BIT_MAX = 2**63 - 1

PATH = "/api/v1/tasks/9f3c"
OTHER_PATH = "/api/v1/tasks/7b21"


def test_the_same_path_and_bytes_hash_the_same() -> None:
    body = b'{"minutes": 45}'

    assert request_fingerprint(PATH, body) == request_fingerprint(PATH, bytes(body))


def test_two_paths_carrying_one_body_hash_differently() -> None:
    # The whole reason the path is in the hash. A claim is keyed by the handler rather than by
    # the resource, so two resources under one key are told apart here or nowhere: a bodyless
    # route addressed by a path parameter has nothing else to differ in.
    assert request_fingerprint(PATH, b"") != request_fingerprint(OTHER_PATH, b"")
    assert request_fingerprint(PATH, b'{"priority": "urgent"}') != request_fingerprint(
        OTHER_PATH, b'{"priority": "urgent"}'
    )


def test_a_body_that_differs_at_all_hashes_differently() -> None:
    # Taken over the raw bytes, before parsing, on purpose. Two bodies that differ only in
    # whitespace are two requests as far as this is concerned, which answers 422 and asks for a
    # new key. The other direction would replay the wrong response.
    assert request_fingerprint(PATH, b'{"minutes": 45}') != request_fingerprint(
        PATH, b'{"minutes":45}'
    )
    assert request_fingerprint(PATH, b'{"minutes": 45}') != request_fingerprint(
        PATH, b'{"minutes": 46}'
    )


def test_the_path_and_the_body_cannot_be_shifted_between_each_other() -> None:
    # A hash over the path concatenated with the body would give one number for a path whose
    # last characters are the body's first, so two different requests would replay each other.
    assert request_fingerprint("/api/v1/tasks/ab", b"c") != request_fingerprint(
        "/api/v1/tasks/a", b"bc"
    )


def test_an_empty_body_still_hashes() -> None:
    # A POST with no body is a real request: a re-solve control sends one.
    assert len(request_fingerprint(PATH, b"")) == 64


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
