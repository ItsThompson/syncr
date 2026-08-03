"""The consent screen's rendering: what it states, and what it cannot be made to state.

The payload is asserted separately in ``test_oauth_services.py``. What is asserted here is the
document: that every scope the payload names reaches the page, that the request can be carried
back, and that a value from a query string cannot become markup. That last one is the reason
this file exists: this is the only page in the product the api renders itself, and it is the one
page whose whole job is to be trusted.
"""

from __future__ import annotations

import re
from dataclasses import replace
from html.parser import HTMLParser

import pytest

from syncr_api.core.scopes import SCOPE_DESCRIPTIONS, Scope
from syncr_api.oauth.authorization import (
    AuthorizeParams,
    ConsentScreen,
    RequestedScope,
    ValidatedAuthorization,
    build_consent_screen,
    validate_authorization,
)
from syncr_api.oauth.config import (
    CLI_CLIENT_ID,
    CLI_CLIENT_NAME,
    CLI_CLIENT_SCOPES,
    CLI_REDIRECT_URIS,
)
from syncr_api.oauth.consent import (
    DECISION_APPROVE,
    DECISION_DENY,
    DECISION_FIELD,
    render_consent_screen,
)
from syncr_api.oauth.pkce import derive_s256_challenge
from syncr_api.oauth.records import ClientRecord

# RFC 7636 appendix B's published verifier, so it is a specification value and not a secret.
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"  # pragma: allowlist secret
CHALLENGE = derive_s256_challenge(VERIFIER)
LOOPBACK = "http://127.0.0.1:54321/callback"
EMAIL = "owner@syncr.test"

CLI_CLIENT = ClientRecord(
    id=CLI_CLIENT_ID,
    name=CLI_CLIENT_NAME,
    redirect_uris=CLI_REDIRECT_URIS,
    allowed_scopes=CLI_CLIENT_SCOPES,
    loopback_only=True,
)


class _Markup(HTMLParser):
    """The tags and attribute names a rendered page actually contains.

    Asserted through a parser rather than by searching the text, because an escaped value
    still CONTAINS the substring `onload=`: what matters is whether the browser would read it
    as an attribute, and only a parser answers that.
    """

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.attributes: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        self.attributes.extend(name for name, _value in attrs)


def markup_of(rendered: str) -> _Markup:
    parsed = _Markup()
    parsed.feed(rendered)
    return parsed


def screen_for(
    *, scope: str, state: str | None = "opaque-state", name: str | None = None
) -> ConsentScreen:
    client = CLI_CLIENT if name is None else replace(CLI_CLIENT, name=name)
    params = AuthorizeParams(
        client_id=client.id,
        redirect_uri=LOOPBACK,
        response_type="code",
        code_challenge=CHALLENGE,
        code_challenge_method="S256",
        scope=scope,
        state=state,
    )
    validated = validate_authorization(params, client)
    assert isinstance(validated, ValidatedAuthorization), validated
    return build_consent_screen(validated, account_email=EMAIL)


def test_the_rendered_page_names_every_requested_scope_and_what_it_grants() -> None:
    rendered = render_consent_screen(screen_for(scope="plan:read plan:write"))

    for scope in (Scope.PLAN_READ, Scope.PLAN_WRITE):
        assert scope.value in rendered
        assert SCOPE_DESCRIPTIONS[scope] in rendered
    assert Scope.ADMIN.value not in rendered, "the page named a scope nobody requested"


def test_the_rendered_page_names_the_client_and_the_account() -> None:
    rendered = render_consent_screen(screen_for(scope="plan:read"))

    assert CLI_CLIENT_NAME in rendered
    assert EMAIL in rendered


def test_the_page_offers_exactly_one_way_to_allow_and_one_to_refuse() -> None:
    rendered = render_consent_screen(screen_for(scope="plan:read"))

    assert rendered.count(f'name="{DECISION_FIELD}" value="{DECISION_APPROVE}"') == 1
    assert rendered.count(f'name="{DECISION_FIELD}" value="{DECISION_DENY}"') == 1
    assert rendered.count('action="/oauth/authorize/decision"') == 2


def test_the_page_carries_the_request_back_so_the_decision_can_re_validate_it() -> None:
    rendered = render_consent_screen(screen_for(scope="plan:read plan:write"))

    for name, value in (
        ("client_id", CLI_CLIENT_ID),
        ("redirect_uri", LOOPBACK),
        ("response_type", "code"),
        ("code_challenge", CHALLENGE),
        ("code_challenge_method", "S256"),
        ("scope", "plan:read plan:write"),
        ("state", "opaque-state"),
    ):
        assert f'name="{name}" value="{value}"' in rendered, f"{name} was not carried back"


def test_a_request_with_no_state_carries_no_state_field() -> None:
    rendered = render_consent_screen(screen_for(scope="plan:read", state=None))

    assert 'name="state"' not in rendered


@pytest.mark.parametrize(
    "hostile",
    [
        '"><script>alert(1)</script>',
        '" onload="alert(1)',
        "<img src=x onerror=alert(1)>",
        "'; document.cookie",
    ],
    ids=["closes the attribute", "adds a handler", "adds an element", "quote injection"],
)
def test_a_hostile_value_from_the_query_string_cannot_become_markup(hostile: str) -> None:
    # Every value on this page arrived in a URL. `state` is the one a client controls freely,
    # so it is the one an attacker would use to turn the consent screen into a script.
    rendered = render_consent_screen(screen_for(scope="plan:read", state=hostile))

    parsed = markup_of(rendered)
    assert "script" not in parsed.tags
    assert "img" not in parsed.tags
    assert [name for name in parsed.attributes if name.startswith("on")] == []
    # Still carried back, as one attribute value, because the client needs its state returned.
    assert rendered.count('name="state"') == 2


def test_a_hostile_client_name_cannot_become_markup() -> None:
    rendered = render_consent_screen(
        screen_for(scope="plan:read", name="<script>alert('registered')</script>")
    )

    assert "script" not in markup_of(rendered).tags
    assert "&lt;script&gt;" in rendered


def test_the_page_states_no_color_and_no_font_family_of_its_own() -> None:
    # `frontend/src/tokens` owns every visual decision in this product. A hex value here
    # would be a second source of truth for one of them, so the page states none: it cannot
    # contradict the token layer by having no opinion.
    rendered = render_consent_screen(screen_for(scope="plan:read"))

    assert re.search(r"#[0-9a-fA-F]{3,8}\b", rendered) is None, "the page states a raw color"
    assert "rgb(" not in rendered
    assert "Playfair" not in rendered
    assert "JetBrains" not in rendered


def test_the_markup_check_reports_a_page_that_did_not_escape() -> None:
    # The control. Without it, "no script tag was parsed" would also hold if the parser saw
    # nothing at all, or if the check were reading the wrong thing.
    unescaped = markup_of('<p><script>alert(1)</script><img src=x onerror="go()"></p>')

    assert "script" in unescaped.tags
    assert "onerror" in unescaped.attributes


def test_the_payload_is_renderable_without_the_validation_that_produced_it() -> None:
    # The payload is the seam a designed surface would consume, so it renders on its own.
    bare = ConsentScreen(
        client_name="Some client",
        account_email=EMAIL,
        scopes=(RequestedScope(name="plan:read", description="Read the plan."),),
        request=AuthorizeParams(
            client_id="some-client",
            redirect_uri=LOOPBACK,
            response_type="code",
            code_challenge=CHALLENGE,
            code_challenge_method="S256",
            scope="plan:read",
        ),
    )

    rendered = render_consent_screen(bare)

    assert "Some client" in rendered
    assert "Read the plan." in rendered
