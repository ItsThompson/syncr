"""The credential's own machinery: encryption at rest, the state parameter, and the token endpoint.

Three modules, one test file, because each is small and all three exist to protect one value: the
refresh token, which is standing authority to read every calendar in the account and to overwrite
the one syncr owns.

What is asserted about encryption is not that Fernet works. It is that a deployment cannot read
another's stored grant, that a value too wide for the column is refused BEFORE the write rather
than at the flush, and that a ciphertext this key cannot read reports that rather than raising: the
answer to all three is a reconnect, and a raise on the read path would be an outage instead.

What is asserted about the state parameter is that every way of getting it wrong is refused: a
forged one, a tampered one, a stale one, and one issued for another tenant. That last is the whole
reason the state carries a tenant at all.

What is asserted about the token endpoint is the distinction the notice volume depends on: an
``invalid_grant`` is a dead grant and everything else is a transport failure. Confusing the two
either raises the loudest notice in the product against a healthy credential, or hides a dead one
behind a retry.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import pytest

from syncr_api.google_account.config import REFRESH_TOKEN_MAX_LENGTH, STATE_LIFETIME
from syncr_api.google_account.crypto import RefreshTokenTooLong, TokenCipher
from syncr_api.google_account.oauth_client import (
    GoogleOAuthClient,
    GrantRefused,
    TokenEndpointUnreachable,
    TokenPayload,
)
from syncr_api.google_account.state import StateAccepted, StateRejected, issue_state, read_state
from tests.fake_google import (
    CLIENT_ID,
    CLIENT_SECRET,
    REDIRECT_URI,
    REFRESH_TOKEN,
    TEST_ENCRYPTION_KEY,
    token_answer,
    token_transport,
)

OTHER_KEY = "YW5vdGhlci1kZXBsb3ltZW50cy1nb29nbGUtdG9rZW4ta2V5"  # pragma: allowlist secret
SIGNING_SECRET = "a-signing-secret-a-deployment-generated"  # pragma: allowlist secret
NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)
TENANT = uuid4()


# --------------------------------------------------------------------------------------
# Encryption at rest
# --------------------------------------------------------------------------------------


def test_a_stored_token_round_trips_under_its_own_key() -> None:
    cipher = TokenCipher(TEST_ENCRYPTION_KEY)

    stored = cipher.encrypt(REFRESH_TOKEN)

    assert stored != REFRESH_TOKEN
    assert REFRESH_TOKEN not in stored
    assert cipher.decrypt(stored) == REFRESH_TOKEN


def test_another_deployments_key_cannot_read_a_stored_token() -> None:
    # The property that makes a database dump inert: the key is in the environment, which is the
    # one place a dump does not reach.
    stored = TokenCipher(TEST_ENCRYPTION_KEY).encrypt(REFRESH_TOKEN)

    assert TokenCipher(OTHER_KEY).decrypt(stored) is None


@pytest.mark.parametrize(
    "corrupted",
    ["", "not-ciphertext", "gAAAAABn-truncated"],
    ids=["empty", "not fernet", "truncated"],
)
def test_a_ciphertext_that_will_not_decrypt_reports_rather_than_raises(corrupted: str) -> None:
    # A dead credential, not an error to swallow: the answer is the same as an expired refresh
    # token, and a raise here would take a read path down over a repair the user can make.
    assert TokenCipher(TEST_ENCRYPTION_KEY).decrypt(corrupted) is None


def test_a_token_wider_than_the_column_is_refused_before_the_write() -> None:
    # The lesson an oversize write taught: it raises at the flush, which rolls back the
    # whole transaction and takes every sibling write with it.
    oversize = "1//" + "x" * REFRESH_TOKEN_MAX_LENGTH

    with pytest.raises(RefreshTokenTooLong, match=str(REFRESH_TOKEN_MAX_LENGTH)):
        TokenCipher(TEST_ENCRYPTION_KEY).encrypt(oversize)


def test_the_oversize_message_states_the_size_rather_than_the_value() -> None:
    oversize = "1//" + "x" * REFRESH_TOKEN_MAX_LENGTH

    with pytest.raises(RefreshTokenTooLong) as refused:
        TokenCipher(TEST_ENCRYPTION_KEY).encrypt(oversize)

    assert oversize not in str(refused.value)


# --------------------------------------------------------------------------------------
# The state parameter
# --------------------------------------------------------------------------------------


def test_a_state_this_process_issued_verifies_to_its_own_tenant() -> None:
    state = issue_state(tenant_id=TENANT, secret=SIGNING_SECRET, at=NOW)

    verdict = read_state(state, secret=SIGNING_SECRET, now=NOW + timedelta(minutes=2))

    assert verdict == StateAccepted(tenant_id=TENANT)


def test_two_states_for_one_tenant_differ() -> None:
    # The nonce is what stops a state being a stable value an attacker can collect once and replay
    # for as long as the secret lives.
    first = issue_state(tenant_id=TENANT, secret=SIGNING_SECRET, at=NOW)
    second = issue_state(tenant_id=TENANT, secret=SIGNING_SECRET, at=NOW)

    assert first != second


@pytest.mark.parametrize(
    "forged",
    ["", "v1.deadbeef.0.nonce.signature", "not-a-state"],
    ids=["empty", "plausible shape", "nonsense"],
)
def test_a_state_this_process_did_not_issue_is_refused(forged: str) -> None:
    verdict = read_state(forged, secret=SIGNING_SECRET, now=NOW)

    assert isinstance(verdict, StateRejected)
    assert "could not be verified" in verdict.reason


def test_a_state_whose_tenant_was_edited_is_refused() -> None:
    # The signature covers the tenant, so swapping it invalidates the whole value rather than
    # producing a state for the tenant the attacker wants.
    state = issue_state(tenant_id=TENANT, secret=SIGNING_SECRET, at=NOW)
    tampered = state.replace(TENANT.hex, uuid4().hex)

    assert isinstance(read_state(tampered, secret=SIGNING_SECRET, now=NOW), StateRejected)


def test_a_state_signed_under_another_secret_is_refused() -> None:
    state = issue_state(tenant_id=TENANT, secret="another-deployments-secret", at=NOW)

    assert isinstance(read_state(state, secret=SIGNING_SECRET, now=NOW), StateRejected)


def test_a_state_older_than_its_lifetime_is_refused_with_what_to_do() -> None:
    state = issue_state(tenant_id=TENANT, secret=SIGNING_SECRET, at=NOW)

    verdict = read_state(state, secret=SIGNING_SECRET, now=NOW + STATE_LIFETIME + timedelta(1))

    assert isinstance(verdict, StateRejected)
    assert "Start it again" in verdict.reason
    assert "still works" in verdict.reason


def test_a_state_dated_in_the_future_is_refused_too() -> None:
    # Unreachable through a state this deployment signed, and one comparison's cost: a clock that
    # moved backwards across a restart is the reachable way to hold one.
    state = issue_state(tenant_id=TENANT, secret=SIGNING_SECRET, at=NOW + STATE_LIFETIME * 2)

    assert isinstance(read_state(state, secret=SIGNING_SECRET, now=NOW), StateRejected)


def test_a_state_at_the_edge_of_its_lifetime_is_still_accepted() -> None:
    state = issue_state(tenant_id=TENANT, secret=SIGNING_SECRET, at=NOW)

    verdict = read_state(state, secret=SIGNING_SECRET, now=NOW + STATE_LIFETIME)

    assert isinstance(verdict, StateAccepted)


# --------------------------------------------------------------------------------------
# The token endpoint
# --------------------------------------------------------------------------------------


def oauth(handler: object) -> GoogleOAuthClient:
    return GoogleOAuthClient(
        client=token_transport(handler),
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
    )


async def test_a_code_exchange_sends_the_client_credentials_and_the_redirect() -> None:
    seen: dict[str, list[str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(parse_qs(request.content.decode()))
        return token_answer()

    answer = await oauth(handler).exchange_code("4/code")

    assert isinstance(answer, TokenPayload)
    assert answer.refresh_token == REFRESH_TOKEN
    assert seen["grant_type"] == ["authorization_code"]
    assert seen["code"] == ["4/code"]
    assert seen["client_id"] == [CLIENT_ID]
    assert seen["client_secret"] == [CLIENT_SECRET]
    # Google matches a redirect URI as an exact string, and the exchange has to present the same
    # one the authorization did.
    assert seen["redirect_uri"] == [REDIRECT_URI]


async def test_a_refresh_asks_for_the_refresh_grant() -> None:
    seen: dict[str, list[str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(parse_qs(request.content.decode()))
        return token_answer(refresh_token=None)

    answer = await oauth(handler).refresh(REFRESH_TOKEN)

    assert isinstance(answer, TokenPayload)
    assert answer.access_token
    assert seen["grant_type"] == ["refresh_token"]
    assert seen["refresh_token"] == [REFRESH_TOKEN]
    # A refresh presents no redirect URI: there is no browser in it.
    assert "redirect_uri" not in seen


async def test_the_granted_scopes_are_read_from_the_answer_rather_than_the_request() -> None:
    # A user may untick a scope on the consent screen, so what was granted can be narrower than
    # what was asked for, and the surface that says what syncr can do reads the answer.
    answer = await oauth(lambda _request: token_answer(scope="a b c")).refresh(REFRESH_TOKEN)

    assert isinstance(answer, TokenPayload)
    assert answer.granted_scopes == ("a", "b", "c")


async def test_an_invalid_grant_is_a_dead_credential() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    answer = await oauth(handler).refresh(REFRESH_TOKEN)

    assert isinstance(answer, GrantRefused)
    assert "revoked, expired, or replaced" in answer.reason


async def test_a_bad_request_of_ours_is_not_reported_as_a_dead_credential() -> None:
    # A 400 is also what a malformed request gets, so the CODE decides rather than the status: this
    # must not tell the user to reconnect a credential that is fine.
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_request"})

    answer = await oauth(handler).refresh(REFRESH_TOKEN)

    assert isinstance(answer, TokenEndpointUnreachable)
    assert "invalid_request" in answer.reason


@pytest.mark.parametrize("status", [500, 502, 503])
async def test_a_server_error_is_a_transport_failure(status: int) -> None:
    answer = await oauth(lambda _r: httpx.Response(status)).refresh(REFRESH_TOKEN)

    assert isinstance(answer, TokenEndpointUnreachable)


async def test_a_connection_failure_is_answered_rather_than_raised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    answer = await oauth(handler).refresh(REFRESH_TOKEN)

    assert isinstance(answer, TokenEndpointUnreachable)
    assert "ConnectError" in answer.reason


async def test_a_timeout_is_answered_rather_than_raised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    answer = await oauth(handler).refresh(REFRESH_TOKEN)

    assert isinstance(answer, TokenEndpointUnreachable)
    assert "did not answer within" in answer.reason


async def test_an_answer_with_no_access_token_is_refused_at_the_boundary() -> None:
    # A provider contract can change under you, so the field every caller needs is required and a
    # body without it is a stated failure rather than a KeyError three layers up.
    answer = await oauth(lambda _r: httpx.Response(200, json={"expires_in": 3599})).refresh(
        REFRESH_TOKEN
    )

    assert isinstance(answer, TokenEndpointUnreachable)
    assert "cannot read" in answer.reason


async def test_an_html_answer_is_refused_rather_than_parsed() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>a proxy said no</html>")

    assert isinstance(await oauth(handler).refresh(REFRESH_TOKEN), TokenEndpointUnreachable)


async def test_an_unknown_field_does_not_break_a_working_answer() -> None:
    # Google adds fields, and refusing an additive change would turn a Google release into an
    # outage.
    answer = await oauth(lambda _r: token_answer(refresh_token_expires_in=604800)).refresh(
        REFRESH_TOKEN
    )

    assert isinstance(answer, TokenPayload)


async def test_a_body_larger_than_any_token_response_is_refused() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * (64 * 1024 + 1))

    answer = await oauth(handler).refresh(REFRESH_TOKEN)

    assert isinstance(answer, TokenEndpointUnreachable)
    assert "larger than" in answer.reason


def test_a_missing_lifetime_does_not_mean_a_token_that_never_expires() -> None:
    payload = TokenPayload(access_token="ya29.x")

    assert payload.lifetime_seconds > 0
