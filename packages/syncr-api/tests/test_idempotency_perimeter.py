"""The document's own idempotency claim, held against the exemption list it declares.

``frontend/openapi.json`` declares ``Idempotency-Key`` on every operation whose dependency tree
resolves a key reader, and ``test_idempotency_contract.py`` crosses those two directions. What that
crossing does not hold is the claim itself: the document tells every client that an unsafe
operation takes a key, and this file makes the document live up to its own sentence. The unsafe
operations declaring no key must be exactly the declared exemptions -- the five auth and OAuth
endpoints whose callers have no session or token yet to mint a key under -- each with its reason
stated beside it in the list.

The comparison reads declarations and writes nothing; it is a tripwire for coverage work, not the
fix. At HEAD it fails: routes still exist outside the guard, which is work in flight rather than
the contract, so the real-document assertion carries a strict xfail behind the tracking ID below.
Strict is what keeps the marker honest: when the last unguarded route joins the guard, the xfail
itself goes red, and the marker is deleted rather than left agreeing with whatever the routes do.

**Asserted by walking each operation's own ``parameters`` list**, for the same reason its sibling
file gives: a text search answers true for a document in which nothing at all is declared.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from syncr_api.idempotency.config import IDEMPOTENCY_KEY_HEADER
from tests.test_alert_rules import repo_root

if TYPE_CHECKING:
    from collections.abc import Mapping

# The committed contract, resolved through the same anchor every figure about it was printed
# against: the installed package, not this file's own depth in the tree.
CONTRACT = repo_root() / "frontend" / "openapi.json"

# The keys of an OpenAPI path item that are operations, shared with the sibling crossing.
OPERATION_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})

# An operation is unsafe when its method can change state, so only these owe the document a key.
SAFE_METHODS = frozenset({"get", "head", "options"})

# The whole of what may answer without a key, one stated reason per entry. An addition needs its
# reason in the same change: the list must not absorb a route merely because guarding it is
# inconvenient. Each entry names an endpoint reached before the caller holds the session or token
# the keyed client is built on, which is why no key can be required of it.
EXEMPTIONS: Mapping[tuple[str, str], str] = {
    ("POST", "/auth/login"): (
        "the request creates the session, so there is no session yet to scope a claim to"
    ),
    ("POST", "/auth/logout"): (
        "the request ends the session, so a claim stored under it could not be read back"
    ),
    ("POST", "/oauth/authorize/decision"): (
        "submitted by the authorization server's own consent page, not by the keyed frontend client"
    ),
    ("POST", "/oauth/revoke"): (
        "issued by whoever holds the token, outside the keyed frontend client"
    ),
    ("POST", "/oauth/token"): (
        "a grant exchange by another server's client, which carries no key discipline of ours"
    ),
}


def unsafe_operations(document: Mapping[str, Any]) -> set[tuple[str, str]]:
    """Every ``(method, path)`` whose method can change state."""
    paths: Mapping[str, Mapping[str, Any]] = document["paths"]
    return {
        (method.upper(), path)
        for path, path_item in paths.items()
        for method in OPERATION_METHODS & path_item.keys()
        if method not in SAFE_METHODS
    }


def declaring_operations(document: Mapping[str, Any]) -> set[tuple[str, str]]:
    """Every ``(method, path)`` whose own parameters list declares the header."""
    paths: Mapping[str, Mapping[str, Mapping[str, Any]]] = document["paths"]
    return {
        (method.upper(), path)
        for path, path_item in paths.items()
        for method in OPERATION_METHODS & path_item.keys()
        if any(
            parameter["in"] == "header" and parameter["name"] == IDEMPOTENCY_KEY_HEADER
            for parameter in path_item[method].get("parameters", ())
        )
    }


def unguarded_unsafe_operations(document: Mapping[str, Any]) -> set[tuple[str, str]]:
    """The unsafe operations declaring no key: what the exemption list must account for."""
    return unsafe_operations(document) - declaring_operations(document)


@pytest.fixture(scope="module")
def contract() -> Mapping[str, Any]:
    document: Mapping[str, Any] = json.loads(CONTRACT.read_text(encoding="utf-8"))
    return document


@pytest.mark.xfail(
    strict=True,
    reason="the contract's claim outruns the guard at HEAD: unsafe operations beyond the five "
    "exemptions declare no key yet (SR-INTENT-02 brings the six preference routes under the "
    "guard; the rest wait for their coverage tickets). This marker goes when the last of them "
    "joins the guard.",
)
def test_every_unsafe_operation_takes_a_key_but_the_five_exempt_ones(
    contract: Mapping[str, Any],
) -> None:
    unguarded = unguarded_unsafe_operations(contract)

    unexpected = sorted(unguarded - EXEMPTIONS.keys())
    unjustified = sorted(EXEMPTIONS.keys() - unguarded)
    assert not unexpected and not unjustified, (
        f"{len(unguarded)} unsafe operations declare no {IDEMPOTENCY_KEY_HEADER}. Unguarded with "
        f"no exemption: {unexpected}. Exempt but now guarded, so its entry should leave the list: "
        f"{unjustified}. Regenerate with `just contract`."
    )


def test_the_census_reaches_declarations_on_the_real_document(
    contract: Mapping[str, Any],
) -> None:
    # The equality above compares two derived sets, so it would hold vacuously through a census
    # that answers nothing at all. This control pins the census to the real document: some unsafe
    # operation must already declare the key, and stay true however far the guard later spreads.
    unsafe = unsafe_operations(contract)

    assert unsafe, "no unsafe operation was found, so nothing was examined"
    assert declaring_operations(contract), (
        "no unsafe operation declares the key, so the reader cannot tell a declaration from "
        "silence on the document it exists to police"
    )
    assert unguarded_unsafe_operations(contract) < unsafe


def test_a_planted_unguarded_operation_is_reported_rather_than_absorbed() -> None:
    # The positive control, over a synthetic document rather than the real one: nothing planted in
    # the tree today can prove the comparison discriminates, because the real document was
    # generated from whatever the guard currently covers. A planted operation with no declaration
    # must surface as unaccounted; declaring the header removes the report; a parameter of another
    # name or another location must not count as the declaration.
    planted = {"paths": {"/planted": {"post": {"summary": "changes something"}}}}
    guarded = {
        "paths": {
            "/planted": {
                "post": {
                    "parameters": [{"in": "header", "name": IDEMPOTENCY_KEY_HEADER}],
                }
            }
        }
    }
    misdeclared = {
        "paths": {
            "/planted": {
                "post": {
                    "parameters": [
                        {"in": "query", "name": IDEMPOTENCY_KEY_HEADER},
                        {"in": "header", "name": "X-Other"},
                    ],
                }
            }
        }
    }

    assert unguarded_unsafe_operations(planted) == {("POST", "/planted")}
    assert unguarded_unsafe_operations(guarded) == set()
    assert unguarded_unsafe_operations(misdeclared) == {("POST", "/planted")}
