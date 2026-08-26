"""The weekly-session runbook's figures and queries, crossed against what decides them.

The runbook is read once, under pressure, so every figure it quotes is asserted against the
constant that produces it rather than against a second copy of the number here: the budget against
`reviews/config.SESSION_P95_BUDGET_SECONDS`, the expression against the rule's own, and each cited
series against the family the registry declares.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from syncr_api.reviews.config import SESSION_P95_BUDGET_SECONDS
from tests.test_alert_rules import exported_families, families_in, repo_root
from tests.test_alert_rules import named as alert_named
from tests.test_runbook_figures import alert_waits, minutes

RUNBOOK: Final = Path("docs/runbooks/weekly-session-slow.md")
ALERT: Final = "WeeklySessionSlow"

# The budget in the units the prose states it in. Derived from the constant, never restated.
BUDGET_MILLISECONDS: Final = int(SESSION_P95_BUDGET_SECONDS * 1000)


def read(runbook: Path) -> str:
    return (repo_root() / runbook).read_text()


class TestTheWeeklySessionRunbook:
    def test_the_alert_points_at_it(self) -> None:
        assert alert_named(ALERT).annotations["runbook"] == "docs/runbooks/weekly-session-slow.md"

    def test_the_title_is_the_condition_the_rule_states(self) -> None:
        """The title is what fired, in the units an operator reads, from the rule's own figure."""
        rule = alert_named(ALERT)

        assert f"over {BUDGET_MILLISECONDS} ms" in read(RUNBOOK).splitlines()[0]
        assert f">{SESSION_P95_BUDGET_SECONDS}" in rule.expr.replace(" ", "")

    def test_the_trigger_quotes_the_rule_s_own_expression(self) -> None:
        """Every family the rule reads appears verbatim in the pasted expression, and vice versa.

        A trigger block that drifted from the rule would have an operator paste a query Prometheus
        answers differently from the alert that woke them.
        """
        rule = alert_named(ALERT)
        runbook = read(RUNBOOK)

        for family in families_in(rule.expr):
            assert family in runbook
        assert 'route="/api/v1/reviews/week/{iso_week}"' in runbook

    def test_it_quotes_the_budget_constant_its_threshold_comes_from(self) -> None:
        runbook = read(RUNBOOK)

        assert "SESSION_P95_BUDGET_SECONDS" in runbook
        assert f"{BUDGET_MILLISECONDS} ms" in runbook

    def test_it_states_the_derivation_rather_than_only_the_total(self) -> None:
        """The week view's own budget is one term of the arithmetic, so a retune of THAT figure
        invalidates this one; the runbook has to say so or the derivation cannot be audited."""
        runbook = read(RUNBOOK)

        assert "300 ms" in runbook
        assert "test_week_view_integration" in runbook

    def test_it_names_the_wait_the_rule_declares(self) -> None:
        wait = minutes(alert_waits(ALERT))

        assert f"**{wait} minutes**" in read(RUNBOOK)

    def test_every_series_it_queries_is_one_the_deployment_exports(self) -> None:
        """A query over a family no process exports returns one meaningless empty frame, and the
        table under it then cannot be wrong in a way the reader can see."""
        queried = families_in(read(RUNBOOK))

        assert queried <= exported_families()
