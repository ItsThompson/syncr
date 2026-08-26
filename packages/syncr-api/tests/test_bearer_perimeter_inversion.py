"""The bearer half of the perimeter inverted, and the direction it removes asserted.

``accounts`` resolves whichever credential a request presents, which makes it naturally the
upper half of the perimeter. It used to reach the bearer resolution by importing
``syncr_api.oauth``, an edge between two feature packages whose direction nothing detected.
The resolution now travels as the state object the entrypoint attaches: ``accounts`` reads
``app.state.oauth`` behind the protocol in ``core.credentials``, names no ``oauth`` type, and
reaches for the state only when a request presents a token, so an application built with no
OAuth state still serves a browser. The refusal and its log line stay in the one place that
mints them, and rule R2 below is what keeps the removed edge removed.

The static rules read the tree as text, so they run in every environment. The two HTTP
assertions drive real routes over a live Postgres, because "exactly once" and "still serves"
are answers about requests, not about source.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.accounts.repository import SessionRepository
from syncr_api.areas.config import AREAS_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.credentials import AUTHORIZATION_HEADER
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.idempotency.config import IDEMPOTENCY_KEY_HEADER
from syncr_api.templates.config import DAY_TYPES_PREFIX
from tests.boundaries import imported_modules
from tests.cli_credentials import BROWSER_ORIGIN
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    import httpx
    from fastapi import FastAPI

    from syncr_api.accounts.records import SessionRecord, UserRecord
    from syncr_api.accounts.session_tokens import SessionId
    from syncr_api.core.settings import ServiceSettings

# A browser-only mutation on a guarded route: its guard resolves the either-credential perimeter
# as a sub-dependency, so one request exercises both declarations that share one session read.
DAY_TYPES_ROUTE = DAY_TYPES_PREFIX
MUTATION_BODY = {"name": "Weekday"}
MUTATION_IDEMPOTENCY_KEY = "inversion-probe"

BEARER_REJECTED_EVENT = "oauth.bearer.rejected"
REFUSAL_DETAIL = "That access token is not valid for this API"


# ---------------------------------------------------------------------------
# Rule R2: accounts imports nothing from syncr_api.oauth.
# ---------------------------------------------------------------------------


def oauth_reach(source: str) -> list[str]:
    """Every ``syncr_api.oauth`` module this source imports, if any."""
    return sorted(name for name in imported_modules(source) if name.startswith("syncr_api.oauth"))


def oauth_violations(root: Path) -> dict[str, list[str]]:
    """Every file under ``root``'s ``accounts`` package importing ``syncr_api.oauth``, by path."""
    modules = sorted((root / "accounts").glob("*.py"))
    return {
        module.relative_to(root).as_posix(): reach
        for module in modules
        if (reach := oauth_reach(module.read_text(encoding="utf-8")))
    }


def test_no_module_in_accounts_imports_anything_from_oauth(source_root: Path) -> None:
    # The walk has to find the real package before the rule can say anything about it, so an
    # empty walk fails loudly instead of passing vacuously.
    assert any((source_root / "accounts").glob("*.py")), "no accounts module was found to examine"

    assert oauth_violations(source_root) == {}, (
        "The two halves of the perimeter meet at app.state.oauth behind the protocol in "
        "core.credentials, never at an import between the packages."
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "from syncr_api.oauth.injection import resolve_bearer_principal",
            ["syncr_api.oauth.injection"],
        ),
        ("import syncr_api.oauth.tokens", ["syncr_api.oauth.tokens"]),
        ("from syncr_api.core.credentials import AccessTokenReader", []),
    ],
    ids=[
        "the import this ticket restored as a control",
        "a plain module import",
        "an allowed core import",
    ],
)
def test_the_rule_reddens_when_the_import_is_restored(source: str, expected: list[str]) -> None:
    assert oauth_reach(source) == expected


def test_the_rule_walk_reddens_on_a_planted_tree(tmp_path: Path) -> None:
    # The detector's own control above proves the reading bites; this one proves the WALK does.
    # A planted tree with the same shape as the real package, holding exactly the import this
    # ticket removed, must be reported by the full rule and not just by the helper it calls.
    (tmp_path / "accounts").mkdir()
    (tmp_path / "accounts" / "injection.py").write_text(
        "from syncr_api.core.credentials import AccessTokenReader\n", encoding="utf-8"
    )
    (tmp_path / "accounts" / "restored.py").write_text(
        "from syncr_api.oauth.injection import resolve_bearer_principal\n", encoding="utf-8"
    )

    assert oauth_violations(tmp_path) == {"accounts/restored.py": ["syncr_api.oauth.injection"]}


def test_the_refusal_and_its_log_line_are_defined_in_one_place(source_root: Path) -> None:
    def sites(needle: str) -> list[str]:
        return sorted(
            found.relative_to(source_root).as_posix()
            for found in source_root.rglob("*.py")
            if needle in found.read_text(encoding="utf-8")
        )

    assert sites(BEARER_REJECTED_EVENT) == ["oauth/tokens.py"]
    assert sites(REFUSAL_DETAIL) == ["oauth/tokens.py"]


# ---------------------------------------------------------------------------
# The behavior, driven over HTTP against a live Postgres.
# ---------------------------------------------------------------------------


@pytest.fixture
def owner(live_database_url: str) -> Iterator[UserRecord]:
    """A tenant with the one user a sign-in needs, created and then removed."""
    account = provision_owner(live_database_url)
    yield account
    remove_tenant(live_database_url, account.tenant_id)


@pytest.fixture
def app(live_database_url: str, settings: ServiceSettings) -> FastAPI:
    """The whole application on the live database, and deliberately nothing on ``state.oauth``."""
    database = create_database(live_database_url)
    built = create_app(settings, lifespan=create_db_lifespan(database.engine))
    built.state.db = database
    return built


@pytest.fixture
def http(app: FastAPI) -> Iterator[TestClient]:
    # raise_server_exceptions=False so the catch-all handler's response is what the test sees,
    # which is what a real client gets.
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def _signed_in(http: TestClient, email: str) -> dict[str, str]:
    """The cookie header a signed-in browser sends."""
    response = http.post(
        f"{AUTH_PREFIX}/login",
        json={"email": email, "password": PASSWORD},
        headers={"Origin": BROWSER_ORIGIN},
    )
    assert response.status_code == 200, response.text
    token = response.headers["set-cookie"].split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


def _one_mutation(http: TestClient, cookie: dict[str, str]) -> httpx.Response:
    """One guarded browser mutation."""
    # Annotated on the way out rather than cast: `TestClient` is typed loosely enough that the
    # response is `Any`, and the caller reads its status.
    answered: httpx.Response = http.post(
        DAY_TYPES_ROUTE,
        json=MUTATION_BODY,
        headers={
            **cookie,
            "Origin": BROWSER_ORIGIN,
            IDEMPOTENCY_KEY_HEADER: MUTATION_IDEMPOTENCY_KEY,
        },
    )
    return answered


def test_an_app_with_no_oauth_state_still_serves_a_cookie_mutation(
    http: TestClient, owner: UserRecord
) -> None:
    cookie = _signed_in(http, owner.email)

    answered = _one_mutation(http, cookie)

    assert answered.status_code == 201, answered.text


def test_a_browser_request_resolves_its_session_exactly_once(
    http: TestClient, owner: UserRecord, monkeypatch: pytest.MonkeyPatch
) -> None:
    cookie = _signed_in(http, owner.email)

    reads = 0
    find = SessionRepository.find

    async def counting_find(self: SessionRepository, session_id: SessionId) -> SessionRecord | None:
        nonlocal reads
        reads += 1
        return await find(self, session_id)

    monkeypatch.setattr(SessionRepository, "find", counting_find)

    answered = _one_mutation(http, cookie)

    assert answered.status_code == 201, answered.text
    assert reads == 1


def test_a_bearer_request_on_an_app_with_no_oauth_state_does_not_fall_back_to_the_session(
    http: TestClient, owner: UserRecord
) -> None:
    # The other direction of the same property: which credential resolves is decided by what the
    # request presents, never by what the application was built with. A bearer header on a
    # perimeter route takes the bearer half even when no OAuth state exists, and faults as the
    # missing attachment it is, rather than degrading into a refusal that tells the client to
    # sign in.
    answered = http.get(
        AREAS_PREFIX,
        headers={"Origin": BROWSER_ORIGIN, AUTHORIZATION_HEADER: "Bearer not-a-token"},
    )

    assert answered.status_code == 500, answered.text
