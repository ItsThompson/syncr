"""The three authorization commands, driven end to end against a real socket.

Each test runs the process's own entrypoint, so what it asserts is the exit code, the bytes on
stdout, the notices on stderr, and what the store holds afterwards. The Authorization Server is a
fake on a real port; the flow, the listener, the PKCE transform, the form encoding, and the token
reading are all the real ones.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import keyring
import pytest

from syncr_cli.auth.discovery import CLIENT_ID, DISCOVERY_PATH, REQUESTED_SCOPES
from syncr_cli.auth.pkce import derive_challenge
from syncr_cli.auth.storage import KEYCHAIN_LOCATION, KEYRING_SERVICE
from syncr_cli.exit_codes import ExitCode
from tests import payloads
from tests.browsers import CODE, approving_browser, authorize_parameters, refusing_browser
from tests.fake_api import Answer, FakeApi
from tests.harness import drive
from tests.keyrings import InMemoryKeyring, NoKeychain

if TYPE_CHECKING:
    from pathlib import Path

STORED_REFRESH = "syncrr_stored"  # pragma: allowlist secret
ROTATED_REFRESH = "syncrr_rotated"  # pragma: allowlist secret


def authorization_server(api: FakeApi) -> FakeApi:
    """A fake Authorization Server that discovers, exchanges, refreshes, and revokes."""
    api.answer("GET", DISCOVERY_PATH, Answer.json(payloads.metadata(api.base_url)))
    api.answer(
        "POST", "/oauth/token", Answer.json(payloads.token_response(refresh=ROTATED_REFRESH))
    )
    api.answer("POST", "/oauth/revoke", Answer.raw(b"", status=200, media_type="text/plain"))
    return api


def test_login_stores_the_refresh_token_in_the_keychain(
    tmp_path: Path, in_memory_keychain: InMemoryKeyring
) -> None:
    with FakeApi() as api:
        authorization_server(api)

        ran = drive(
            ["auth", "login"],
            base_url=api.base_url,
            home=tmp_path,
            open_browser=approving_browser(),
        )

    assert ran.code is ExitCode.SUCCESS
    assert in_memory_keychain.stored[(KEYRING_SERVICE, api.base_url)] == ROTATED_REFRESH
    assert ran.document["data"]["tokenStore"] == KEYCHAIN_LOCATION
    assert ran.document["data"]["scopes"] == list(REQUESTED_SCOPES)
    assert ran.document["ok"] is True


def test_login_sends_the_s256_challenge_for_the_verifier_it_exchanges(tmp_path: Path) -> None:
    # The whole point of PKCE: the challenge on the authorize request and the verifier on the token
    # request are two halves of one secret, and only the client that started the flow holds both.
    opened: list[str] = []

    with FakeApi() as api:
        authorization_server(api)

        drive(
            ["auth", "login"],
            base_url=api.base_url,
            home=tmp_path,
            open_browser=approving_browser(calls=opened),
        )

        exchange = api.requests_to("POST", "/oauth/token")[0].form

    stated = authorize_parameters(opened[0])
    assert stated["code_challenge_method"] == "S256"
    assert stated["code_challenge"] == derive_challenge(exchange["code_verifier"])
    assert exchange["code"] == CODE
    assert exchange["grant_type"] == "authorization_code"
    assert exchange["client_id"] == CLIENT_ID
    assert exchange["redirect_uri"] == stated["redirect_uri"]


def test_login_requests_the_plan_scopes_and_never_admin(tmp_path: Path) -> None:
    # What makes the out-of-scope list a boundary rather than a suggestion: a stolen CLI token
    # cannot reach calendar setup or template editing however the request is spelled.
    opened: list[str] = []

    with FakeApi() as api:
        authorization_server(api)

        drive(
            ["auth", "login"],
            base_url=api.base_url,
            home=tmp_path,
            open_browser=approving_browser(calls=opened),
        )

    requested = authorize_parameters(opened[0])["scope"].split()
    assert requested == ["plan:read", "plan:write"]
    assert "admin" not in requested


def test_login_redirects_to_a_loopback_port_that_is_not_registered(tmp_path: Path) -> None:
    opened: list[str] = []

    with FakeApi() as api:
        authorization_server(api)

        drive(
            ["auth", "login"],
            base_url=api.base_url,
            home=tmp_path,
            open_browser=approving_browser(calls=opened),
        )

    redirect = authorize_parameters(opened[0])["redirect_uri"]
    assert redirect.startswith("http://127.0.0.1:")
    assert redirect.endswith("/callback")


def test_a_machine_with_no_browser_is_told_where_the_consent_screen_is(tmp_path: Path) -> None:
    # A browser that opened on another display, or a machine with none, leaves the user with a
    # listener and no idea what it is waiting for. So the URL is stated and the wait continues.
    opened: list[str] = []

    with FakeApi() as api:
        authorization_server(api)

        ran = drive(
            ["auth", "login"],
            base_url=api.base_url,
            home=tmp_path,
            open_browser=approving_browser(opens=False, calls=opened),
        )

    assert ran.code is ExitCode.SUCCESS
    assert "Open this URL" in ran.stderr
    assert opened[0] in ran.stderr


def test_login_on_a_machine_with_no_keychain_falls_back_and_says_so(tmp_path: Path) -> None:
    keyring.set_keyring(NoKeychain())

    with FakeApi() as api:
        authorization_server(api)

        ran = drive(
            ["auth", "login"],
            base_url=api.base_url,
            home=tmp_path,
            open_browser=approving_browser(),
        )

    assert ran.code is ExitCode.SUCCESS
    assert ran.document["data"]["tokenStoreIsFallback"] is True
    assert "0600" in ran.stderr
    stored = tmp_path / ".config" / "syncr" / "credentials.json"
    assert ROTATED_REFRESH in stored.read_text(encoding="utf-8")


def test_a_refusal_on_the_redirect_is_reported_and_nothing_is_stored(
    tmp_path: Path, in_memory_keychain: InMemoryKeyring
) -> None:
    with FakeApi() as api:
        authorization_server(api)

        ran = drive(
            ["auth", "login"],
            base_url=api.base_url,
            home=tmp_path,
            open_browser=refusing_browser(error="invalid_scope", description="admin refused"),
        )

    assert ran.code is ExitCode.FAILURE
    assert "invalid_scope" in ran.document["problem"]["detail"]
    assert in_memory_keychain.stored == {}
    assert api.requests_to("POST", "/oauth/token") == []


def test_a_redirect_carrying_another_flows_state_is_refused(tmp_path: Path) -> None:
    with FakeApi() as api:
        authorization_server(api)

        ran = drive(
            ["auth", "login"],
            base_url=api.base_url,
            home=tmp_path,
            open_browser=approving_browser(state="another-flow"),
        )

    assert ran.code is ExitCode.USAGE
    assert api.requests_to("POST", "/oauth/token") == []


def test_a_server_that_does_not_advertise_s256_is_refused(tmp_path: Path) -> None:
    weak = payloads.metadata("http://localhost")
    weak["code_challenge_methods_supported"] = ["plain"]

    with FakeApi() as api:
        api.answer("GET", DISCOVERY_PATH, Answer.json(weak))

        ran = drive(
            ["auth", "login"],
            base_url=api.base_url,
            home=tmp_path,
            open_browser=approving_browser(),
        )

    assert ran.code is ExitCode.FAILURE
    assert "S256" in ran.document["problem"]["detail"]


def test_status_reports_the_principal_and_the_granted_scopes(
    tmp_path: Path, in_memory_keychain: InMemoryKeyring
) -> None:
    with FakeApi() as api:
        authorization_server(api)
        in_memory_keychain.stored[(KEYRING_SERVICE, api.base_url)] = STORED_REFRESH

        ran = drive(["auth", "status"], base_url=api.base_url, home=tmp_path)

    data = ran.document["data"]
    assert ran.code is ExitCode.SUCCESS
    assert data["tenantId"] == payloads.TENANT_ID
    assert data["userId"] == payloads.USER_ID
    assert data["scopes"] == list(REQUESTED_SCOPES)
    assert data["clientId"] == CLIENT_ID


def test_status_refreshes_the_stored_grant_and_stores_the_successor(
    tmp_path: Path, in_memory_keychain: InMemoryKeyring
) -> None:
    # The refresh rotates: presenting a consumed token revokes the whole family, so the successor
    # has to replace it in the store before anything else happens.
    with FakeApi() as api:
        authorization_server(api)
        in_memory_keychain.stored[(KEYRING_SERVICE, api.base_url)] = STORED_REFRESH

        drive(["auth", "status"], base_url=api.base_url, home=tmp_path)

        exchange = api.requests_to("POST", "/oauth/token")[0].form

    assert exchange == {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "refresh_token": STORED_REFRESH,
    }
    assert in_memory_keychain.stored[(KEYRING_SERVICE, api.base_url)] == ROTATED_REFRESH


def test_status_on_a_machine_that_holds_nothing_exits_three_and_says_what_to_run(
    tmp_path: Path,
) -> None:
    with FakeApi() as api:
        authorization_server(api)

        ran = drive(["auth", "status"], base_url=api.base_url, home=tmp_path)

    assert ran.code is ExitCode.NOT_AUTHENTICATED
    assert "syncr auth login" in ran.document["problem"]["detail"]


def test_a_refresh_the_server_refuses_exits_three_and_says_what_to_run(
    tmp_path: Path, in_memory_keychain: InMemoryKeyring
) -> None:
    with FakeApi() as api:
        authorization_server(api)
        api.answer(
            "POST",
            "/oauth/token",
            Answer.problem(
                payloads.problem(
                    problem_type="syncr:oauth-invalid-grant",
                    status=400,
                    detail="the presented grant is invalid",
                ),
                status=400,
            ),
        )
        in_memory_keychain.stored[(KEYRING_SERVICE, api.base_url)] = STORED_REFRESH

        ran = drive(["auth", "status"], base_url=api.base_url, home=tmp_path)

    assert ran.code is ExitCode.NOT_AUTHENTICATED
    assert "syncr auth login" in ran.document["problem"]["detail"]


def test_logout_revokes_server_side_before_removing_the_local_token(
    tmp_path: Path, in_memory_keychain: InMemoryKeyring
) -> None:
    # Deleting a local file leaves a live grant, which is the whole reason this command talks to the
    # server at all.
    with FakeApi() as api:
        authorization_server(api)
        in_memory_keychain.stored[(KEYRING_SERVICE, api.base_url)] = STORED_REFRESH

        ran = drive(["auth", "logout"], base_url=api.base_url, home=tmp_path)

        revocation = api.requests_to("POST", "/oauth/revoke")[0].form

    assert ran.code is ExitCode.SUCCESS
    assert revocation == {"token": STORED_REFRESH, "client_id": CLIENT_ID}
    assert in_memory_keychain.stored == {}
    assert ran.document["data"]["revoked"] is True


def test_logout_that_cannot_revoke_leaves_the_token_where_it_was(
    tmp_path: Path, in_memory_keychain: InMemoryKeyring
) -> None:
    # A user told the grant is dead must not also have lost the credential that would let them try
    # again.
    with FakeApi() as api:
        authorization_server(api)
        api.answer(
            "POST",
            "/oauth/revoke",
            Answer.problem(
                payloads.problem(problem_type="syncr:dependency-unavailable", status=503),
                status=503,
            ),
        )
        in_memory_keychain.stored[(KEYRING_SERVICE, api.base_url)] = STORED_REFRESH

        ran = drive(["auth", "logout"], base_url=api.base_url, home=tmp_path)

    assert ran.code is ExitCode.API_UNAVAILABLE
    assert in_memory_keychain.stored[(KEYRING_SERVICE, api.base_url)] == STORED_REFRESH


def test_logout_on_a_machine_that_holds_nothing_says_so_and_succeeds(tmp_path: Path) -> None:
    with FakeApi() as api:
        authorization_server(api)

        ran = drive(["auth", "logout"], base_url=api.base_url, home=tmp_path)

    assert ran.code is ExitCode.SUCCESS
    assert ran.document["data"]["revoked"] is False
    assert api.requests_to("POST", "/oauth/revoke") == []


@pytest.mark.parametrize("variable", ["SYNCR_REFRESH_TOKEN", "SYNCR_TOKEN", "SYNCR_ACCESS_TOKEN"])
def test_no_credential_is_read_from_the_environment(tmp_path: Path, variable: str) -> None:
    # The refresh token never touches an environment variable: both the environment and the shell
    # history are readable by other processes and both leak into logs. So a variable that looks like
    # one changes nothing, and the command still says this machine holds no authorization.
    with FakeApi() as api:
        authorization_server(api)

        ran = drive(
            ["auth", "status"],
            base_url=api.base_url,
            home=tmp_path,
            env={variable: STORED_REFRESH},
        )

    assert ran.code is ExitCode.NOT_AUTHENTICATED


def test_no_secret_reaches_either_stream(
    tmp_path: Path, in_memory_keychain: InMemoryKeyring
) -> None:
    # The strongest form of the rule: whatever the flow minted, none of it is in the output. The
    # access token is searched for too, because it is the one a login has in hand.
    with FakeApi() as api:
        authorization_server(api)

        ran = drive(
            ["auth", "login"],
            base_url=api.base_url,
            home=tmp_path,
            open_browser=approving_browser(),
        )
        exchanged = api.requests_to("POST", "/oauth/token")[0].form

    minted = [ROTATED_REFRESH, CODE, exchanged["code_verifier"], payloads.access_token()]
    for secret in minted:
        assert secret not in ran.stdout
        assert secret not in ran.stderr
