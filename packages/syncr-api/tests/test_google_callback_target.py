"""Where the Google callback sends the browser, and how that address is decided.

Google addresses the callback at the api's own origin, because a registered redirect URI is matched
as an exact string. That origin is not necessarily where the browser application is served: the
deployed stack serves the api and the application through one hostname, and a development stack
serves the application on ``:5173`` while the api answers on ``:8000``. A relative ``Location``
resolves against the origin the request arrived at, so on a split-origin stack it names a path the
api does not serve.

**The claim is a conjunction, and either half can fail alone**, so both are asserted here:

- the callback's target is built from the origin the application is served from, and
- that origin is resolved from the layers that can decide it, in the order they decide it.

Five things can decide it, and they are proved rather than assumed: a real environment variable, the
root environment file, an empty value from an unset interpolation, the field's own default, and
``PUBLIC_BASE_URL``, which the default reads. The two settings are also crossed against each other,
because a swap between them is invisible on a stack where both hold one value.
"""

from __future__ import annotations

from http import HTTPStatus
from itertools import takewhile
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from syncr_api.accounts.injection import require_client_principal
from syncr_api.calendars.config import CALENDAR_SOURCES_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import ALL_SCOPES
from syncr_api.core.settings import (
    API_SERVICE,
    DEV_PUBLIC_BASE_URL,
    EnvSettings,
    build_service_settings,
)
from syncr_api.google_account.config import CALLBACK_PATH
from syncr_api.google_account.injection import get_google_connection_service
from syncr_api.google_account.outcomes import (
    CONNECTED,
    DENIED,
    OUTCOME_QUERY_KEY,
    SETTINGS_PATH,
    settings_url,
)
from syncr_api.google_account.wiring import build_google_account_router
from syncr_api.oauth.config import build_oauth_config
from syncr_common.config import ROOT_ENV_FILE

if TYPE_CHECKING:
    from pathlib import Path

    from syncr_api.core.settings import ServiceSettings
    from syncr_api.google_account.outcomes import ConnectOutcome
    from syncr_api.google_account.service import GoogleConnectionService

# The two shapes the epic names. The deployed stack is one origin for both; a development stack runs
# the Vite dev server beside an api that answers on its own port.
DEPLOYED_ORIGIN = "https://syncr.example"
DEVELOPMENT_APP_ORIGIN = "http://localhost:5173"
DEVELOPMENT_API_ORIGIN = DEV_PUBLIC_BASE_URL

# The documented template a developer copies to `.env`, resolved from the module that resolves the
# file it becomes, so a test finds it whichever directory pytest was started from.
EXAMPLE_ENVIRONMENT_FILE = ROOT_ENV_FILE.with_name(".env.example")


def env(**overrides: object) -> EnvSettings:
    """Settings from explicit values only, so a developer's .env cannot change a test."""
    return EnvSettings(_env_file=None, **overrides)  # type: ignore[arg-type]


def a_deployment(**overrides: object) -> ServiceSettings:
    """One process's settings, which is what a request reads from ``app.state``."""
    return build_service_settings(service=API_SERVICE, env=env(**overrides))


class ConnectThatEnded:
    """The service the callback route calls, answering one stated outcome.

    The route's own job is to map an outcome onto a redirect, so what the exchange did is another
    suite's subject and a real service here would need a database to say anything at all.
    """

    def __init__(self, outcome: ConnectOutcome) -> None:
        self._outcome = outcome

    async def complete_connect(
        self,
        principal: Principal,
        *,
        code: str | None,
        state: str | None,
        error: str | None,
    ) -> ConnectOutcome:
        return self._outcome


def callback_location(settings: ServiceSettings, outcome: ConnectOutcome = CONNECTED) -> str:
    """The ``Location`` the callback answers on this deployment, as the browser receives it."""
    app = create_app(settings, feature_routers=(build_google_account_router,))
    app.dependency_overrides[require_client_principal] = lambda: Principal(
        tenant_id=uuid4(), user_id=uuid4(), scopes=ALL_SCOPES
    )
    app.dependency_overrides[get_google_connection_service] = lambda: cast(
        "GoogleConnectionService", ConnectThatEnded(outcome)
    )
    with TestClient(app, raise_server_exceptions=False) as http:
        answered = http.get(
            f"{CALENDAR_SOURCES_PREFIX}{CALLBACK_PATH}",
            params={"code": "4/code", "state": "signed"},
            follow_redirects=False,
        )

    assert answered.status_code == HTTPStatus.SEE_OTHER, answered.text
    location: str = answered.headers["location"]
    return location


# --------------------------------------------------------------------------------------
# The redirect target, on the two deployment shapes
# --------------------------------------------------------------------------------------


def test_a_split_origin_development_stack_returns_the_browser_to_the_app() -> None:
    """The defect this closes: the app is on :5173 and Google returns the browser to :8000.

    A relative target resolves against the api's origin, which serves no `/settings`, so the flow
    ends on a 404 having stored the grant.
    """
    development = a_deployment(
        app_base_url=DEVELOPMENT_APP_ORIGIN, public_base_url=DEVELOPMENT_API_ORIGIN
    )

    assert (
        callback_location(development)
        == f"{DEVELOPMENT_APP_ORIGIN}{SETTINGS_PATH}?{OUTCOME_QUERY_KEY}={CONNECTED}"
    )


def test_a_same_origin_deployment_lands_where_a_relative_target_used_to() -> None:
    """One origin serves both, so the absolute target names the host the browser already had."""
    deployed = a_deployment(public_base_url=DEPLOYED_ORIGIN)

    assert (
        callback_location(deployed)
        == f"{DEPLOYED_ORIGIN}{SETTINGS_PATH}?{OUTCOME_QUERY_KEY}={CONNECTED}"
    )


@pytest.mark.parametrize("outcome", [CONNECTED, DENIED])
def test_every_outcome_is_carried_to_the_app_origin(outcome: ConnectOutcome) -> None:
    """The origin is the route's, not the outcome's: a refusal has a Settings surface too."""
    development = a_deployment(app_base_url=DEVELOPMENT_APP_ORIGIN)

    assert callback_location(development, outcome).startswith(DEVELOPMENT_APP_ORIGIN)
    assert callback_location(development, outcome).endswith(f"{OUTCOME_QUERY_KEY}={outcome}")


def test_the_target_is_absolute_on_a_split_origin_stack_and_names_the_app_host() -> None:
    """Absoluteness is the property, stated separately from the exact string.

    A target that stayed relative would satisfy no reading of the app's origin, and a target built
    from the api's origin would be absolute and still wrong.
    """
    location = callback_location(a_deployment(app_base_url=DEVELOPMENT_APP_ORIGIN))

    assert location.startswith("http://")
    assert location.startswith(DEVELOPMENT_APP_ORIGIN)
    assert not location.startswith(DEVELOPMENT_API_ORIGIN)


def test_a_base_url_with_a_trailing_slash_does_not_double_the_path_separator() -> None:
    """`.env.example` documents no trailing slash, and an operator supplies one anyway."""
    location = callback_location(a_deployment(app_base_url=f"{DEVELOPMENT_APP_ORIGIN}/"))

    assert location == f"{DEVELOPMENT_APP_ORIGIN}{SETTINGS_PATH}?{OUTCOME_QUERY_KEY}={CONNECTED}"
    assert "//settings" not in location


# --------------------------------------------------------------------------------------
# The two settings, held to their two purposes
# --------------------------------------------------------------------------------------


def test_each_setting_is_read_for_its_own_purpose_and_not_the_other() -> None:
    """The crossing test. On a stack where both hold one value, a swap is invisible.

    ``PUBLIC_BASE_URL`` is the origin every OAuth URL and token claim is built from, and it stays
    that. The new setting decides one redirect. Driven with two different values, so reading either
    for the other's purpose fails here.
    """
    split = a_deployment(
        app_base_url=DEVELOPMENT_APP_ORIGIN, public_base_url=DEVELOPMENT_API_ORIGIN
    )

    oauth = build_oauth_config(split, is_dev=True)

    assert oauth.issuer == DEVELOPMENT_API_ORIGIN
    assert oauth.audience.startswith(DEVELOPMENT_API_ORIGIN)
    assert oauth.endpoint("/oauth", "/token").startswith(DEVELOPMENT_API_ORIGIN)
    assert callback_location(split).startswith(DEVELOPMENT_APP_ORIGIN)


# --------------------------------------------------------------------------------------
# How the app's origin is decided, and in what order
# --------------------------------------------------------------------------------------


def test_the_default_is_the_api_s_own_origin_so_a_deployment_needs_no_new_value() -> None:
    """The whole no-change-by-construction claim: unset means "the origin the api answers on"."""
    assert env().app_base_url == env().public_base_url


def test_the_default_follows_a_supplied_public_base_url_rather_than_the_development_constant() -> (
    None
):
    """A default read off the constant would be right in development and wrong everywhere else."""
    assert env(public_base_url=DEPLOYED_ORIGIN).app_base_url == DEPLOYED_ORIGIN


def test_an_empty_value_falls_back_rather_than_producing_a_target_with_no_host() -> None:
    """An unset compose interpolation is an EMPTY value that overrides the file it came from.

    `docker-compose.yml` says so where it declines to name two other variables. An empty value here
    would rebuild the relative target this seam exists to replace, silently.
    """
    assert env(app_base_url="").app_base_url == env().public_base_url
    assert env(app_base_url="   ").app_base_url == env().public_base_url


def test_a_supplied_value_is_carried_verbatim() -> None:
    assert env(app_base_url=DEVELOPMENT_APP_ORIGIN).app_base_url == DEVELOPMENT_APP_ORIGIN


def test_a_process_carries_the_setting_through_to_the_view_a_request_reads() -> None:
    """A field that stopped at `EnvSettings` would be a field no dependency could see."""
    assert a_deployment(app_base_url=DEVELOPMENT_APP_ORIGIN).app_base_url == DEVELOPMENT_APP_ORIGIN


def test_the_environment_file_decides_it_when_no_variable_is_set(tmp_path: Path) -> None:
    """`just dev-api` runs on the host with no variable set, and the root .env is what it reads."""
    file = tmp_path / ".env"
    file.write_text(f"APP_BASE_URL={DEVELOPMENT_APP_ORIGIN}\n", encoding="utf-8")

    assert EnvSettings(_env_file=file).app_base_url == DEVELOPMENT_APP_ORIGIN


def test_a_real_environment_variable_beats_the_environment_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Compose hands the container both, so the precedence between them decides the address.

    Proved rather than assumed: this is the layer that makes an overlay's stated value authoritative
    over whatever a developer's file happens to hold.
    """
    file = tmp_path / ".env"
    file.write_text(f"APP_BASE_URL={DEVELOPMENT_APP_ORIGIN}\n", encoding="utf-8")
    monkeypatch.setenv("APP_BASE_URL", DEPLOYED_ORIGIN)

    assert EnvSettings(_env_file=file).app_base_url == DEPLOYED_ORIGIN


# --------------------------------------------------------------------------------------
# The function the route calls
# --------------------------------------------------------------------------------------


def test_the_target_is_a_function_of_the_origin_it_is_given() -> None:
    """One expression, no branch: the same outcome answers two origins two ways."""
    assert settings_url(CONNECTED, app_base_url=DEPLOYED_ORIGIN).startswith(DEPLOYED_ORIGIN)
    assert settings_url(CONNECTED, app_base_url=DEVELOPMENT_APP_ORIGIN).startswith(
        DEVELOPMENT_APP_ORIGIN
    )


# --------------------------------------------------------------------------------------
# The file a developer copies
# --------------------------------------------------------------------------------------


def the_comment_block_above(key: str) -> str:
    """The contiguous comment lines a key is declared under in the example environment file."""
    lines = EXAMPLE_ENVIRONMENT_FILE.read_text(encoding="utf-8").splitlines()
    declared = next(index for index, line in enumerate(lines) if line.startswith(f"{key}="))
    above = takewhile(lambda line: line.startswith("#"), reversed(lines[:declared]))
    return "\n".join(above)


def test_the_example_file_ships_the_split_the_development_stack_runs() -> None:
    """Read by the settings class rather than by a pattern, which is what a developer's copy is."""
    documented = EnvSettings(_env_file=EXAMPLE_ENVIRONMENT_FILE)

    assert documented.app_base_url == DEVELOPMENT_APP_ORIGIN
    assert documented.app_base_url != documented.public_base_url


def test_the_example_file_states_the_distinction_where_it_declares_the_key() -> None:
    """A value explained somewhere else in the file is a value a reader sets by guessing."""
    assert "PUBLIC_BASE_URL" in the_comment_block_above("APP_BASE_URL")
