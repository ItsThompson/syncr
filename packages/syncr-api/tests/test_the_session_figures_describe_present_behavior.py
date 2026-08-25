"""The two session-mode figures' artifacts say what the figures read now, and are pinned there.

Three artifacts once asserted a cause that has closed: that no client sends the weekly-session
header, so the engagement streak and the early-catch numerator sit structurally at zero. A client
sends the header with its scheduling acts, the act carries the statement to its verdict rows, and
the figures follow it. Text asserting the closed cause drifts back silently unless something bites,
so this file is the thing that bites: it reads the runner's own module docstring and the dashboard
as deployed, forbids the closed cause in both, and requires each site to state the present read,
with the early-catch panel keeping the one attribution limit that remains true.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import syncr_api

# The runner is resolved from the installed package; the dashboard is resolved from THIS FILE's
# location in the source tree, because an installed package cannot see deployments/.
RUNNER = Path(syncr_api.__file__).resolve().parent / "observability" / "product_runner.py"
DASHBOARD = (
    Path(__file__).resolve().parents[3] / "deployments" / "grafana" / "dashboards" / "product.json"
)

# Phrases that assert the closed cause: no sender, a structurally zero figure, or the ticket that
# once carried the fix. None of them may appear in either artifact again.
CLAIMS_OF_THE_CLOSED_CAUSE = (
    "structurally zero",
    "reads zero",
    "no client sends",
    "ticket ",
)


def runner_docstring() -> str:
    """The runner's module docstring, read from source so the pin holds on the file as written."""
    text = RUNNER.read_text()
    # The module opens and closes its docstring with triple double quotes.
    return text.partition('"""')[2].partition('"""')[0]


def panels() -> list[dict[str, Any]]:
    parsed: dict[str, Any] = json.loads(DASHBOARD.read_text())
    return list(parsed["panels"])


def panel_titled(fragment: str) -> dict[str, Any]:
    found = [panel for panel in panels() if fragment in panel["title"].lower()]
    assert len(found) == 1, f"expected exactly one panel titled like {fragment!r}"
    return found[0]


class TestTheSessionModeFiguresDescribePresentBehavior:
    def test_no_site_still_asserts_the_closed_cause(self) -> None:
        for site_name, text in (
            ("product_runner.py docstring", runner_docstring()),
            ("product.json", DASHBOARD.read_text()),
        ):
            for claim in CLAIMS_OF_THE_CLOSED_CAUSE:
                assert claim not in text.lower(), f"{site_name} still says {claim!r}"

    def test_the_streak_panel_says_where_its_session_half_reads_from(self) -> None:
        """A week's session half follows what clients state, which is present-tense behavior."""
        description = panel_titled("engagement streak")["description"].lower()

        assert "weekly-session header" in description
        assert "client sends" in description
        # The corrected claim, stated positively: the figure follows what acts state. The old text
        # also contained "client sends", so only this phrase separates present from closed cause.
        assert "acts state the session" in description

    def test_the_caught_early_panel_keeps_the_attribution_limit(self) -> None:
        """The limitation that survives the closed cause: an unflagged opening act reads as late."""
        description = panel_titled("caught early")["description"].lower()

        assert "client sends" in description
        assert "no session flag" in description
        assert "late discovery" in description

    def test_the_runner_says_where_the_session_statement_comes_from(self) -> None:
        """The substrate and its journey are stated in the present tense, with the same limit."""
        docstring = runner_docstring().lower()

        assert "session_mode_active" in docstring
        # The provenance statement, keyed on a phrase only the corrected text contains.
        assert "client states" in docstring
        assert "no session flag" in docstring
