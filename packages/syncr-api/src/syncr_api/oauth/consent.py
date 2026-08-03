"""The consent screen, rendered.

This is the one HTML surface the api owns, and it exists because the flow needs it: the
client opens a browser at the authorize endpoint, and a browser shown a JSON body has no
button to press. Every other screen in the product is the SPA's.

**It states no color, no font family beyond the system's monospace stack, and no measurement
that carries meaning.** ``docs/DESIGN-LANGUAGE.md`` and ``frontend/src/tokens`` own every
visual decision in this product, and copying two hex values into a backend template would
make a second source of truth for a decision that has an owner. So the page is deliberately
plain, which cannot contradict the token layer, rather than approximately syncr, which
would. :class:`~syncr_api.oauth.authorization.ConsentScreen` is a payload rather than a
template's locals precisely so a designed surface can render the same values later without
any rule moving.

**Every interpolated value is escaped.** The client's name, the scopes, the state, and the
redirect URI all reach this document from a query string, so escaping is not diligence here:
it is the difference between a consent screen and a script-injection vector on the one page
in the product whose whole job is to be trusted.
"""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING

from syncr_api.oauth.config import CONSENT_DECISION_PATH, OAUTH_PREFIX

if TYPE_CHECKING:
    from syncr_api.oauth.authorization import AuthorizeParams, ConsentScreen

HTML_MEDIA_TYPE = "text/html; charset=utf-8"

# The two values the decision endpoint reads to tell approval from refusal. A single field
# with two values, so a form cannot submit both or neither.
DECISION_FIELD = "decision"
DECISION_APPROVE = "approve"
DECISION_DENY = "deny"

_DECISION_ACTION = f"{OAUTH_PREFIX}{CONSENT_DECISION_PATH}"

_STYLE = """
      body { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
             line-height: 1.55; margin: 0; padding: 3rem 1.5rem; }
      main { max-width: 34rem; margin: 0 auto; }
      h1 { font-size: 1rem; font-weight: 600; }
      dl { margin: 1.5rem 0; }
      dt { font-size: 0.8rem; letter-spacing: 0.08em; text-transform: uppercase; }
      dd { margin: 0.25rem 0 1.25rem 0; }
      form { display: inline; }
      button { font: inherit; padding: 0.4rem 1.2rem; }
"""


def render_consent_screen(screen: ConsentScreen) -> str:
    """The consent page for ``screen``: what is being asked, by whom, and for what.

    The scope list is the substance. A screen that said only "syncr CLI wants access" would
    be asking the user to consent to something nobody stated, so every requested scope is
    named and each one says in plain words what it lets the client do.
    """
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Authorize {escape(screen.client_name)}</title>
    <style>{_STYLE}</style>
  </head>
  <body>
    <main>
      <h1>{escape(screen.client_name)} is asking for access to your syncr plan</h1>
      <p>Signed in as {escape(screen.account_email)}.</p>
      <dl>
{_render_scopes(screen)}
      </dl>
      <form method="post" action="{escape(_DECISION_ACTION)}">
{_render_hidden_fields(screen.request)}
        <button type="submit" name="{DECISION_FIELD}" value="{DECISION_APPROVE}">Allow</button>
      </form>
      <form method="post" action="{escape(_DECISION_ACTION)}">
{_render_hidden_fields(screen.request)}
        <button type="submit" name="{DECISION_FIELD}" value="{DECISION_DENY}">Refuse</button>
      </form>
    </main>
  </body>
</html>
"""


def _render_scopes(screen: ConsentScreen) -> str:
    return "\n".join(
        f"        <dt>{escape(scope.name)}</dt>\n        <dd>{escape(scope.description)}</dd>"
        for scope in screen.scopes
    )


def _render_hidden_fields(request: AuthorizeParams) -> str:
    """The request, carried back so the decision endpoint can re-validate it.

    The form carries the request rather than the server parking it under an opaque id. The
    decision endpoint applies every authorize rule again, so these fields are a payload and
    not a capability: editing one produces a different request that has to pass the same
    rules, and a request from another origin is refused before any of them is read.
    """
    fields = {
        "client_id": request.client_id,
        "redirect_uri": request.redirect_uri,
        "response_type": request.response_type,
        "code_challenge": request.code_challenge,
        "code_challenge_method": request.code_challenge_method,
        "scope": request.scope,
    }
    if request.state is not None:
        fields["state"] = request.state
    return "\n".join(
        f'        <input type="hidden" name="{name}" value="{escape(value, quote=True)}">'
        for name, value in fields.items()
    )
