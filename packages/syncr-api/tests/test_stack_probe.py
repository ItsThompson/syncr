"""Unit tests for the running-stack monitoring probe."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Protocol, cast

import pytest


class StackProbe(Protocol):
    def declared_rule_count(self, alerts_path: Path | None = None) -> int: ...

    def report_rules(self, base: str) -> bool: ...


def load_stack_probe() -> StackProbe:
    path = Path(__file__).resolve().parents[3] / "deployments" / "bin" / "stack-probe.py"
    spec = spec_from_file_location("stack_probe", path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast("StackProbe", module)


def test_declared_rule_count_reads_the_alert_file(tmp_path: Path) -> None:
    alerts_path = tmp_path / "alerts.yml"
    alerts_path.write_text(
        """groups:
  - name: probe
    rules:
      - alert: FirstAlert
      - alert: SecondAlert
"""
    )

    assert load_stack_probe().declared_rule_count(alerts_path) == 2


@pytest.mark.parametrize("missing_rules", [0, 1])
def test_report_rules_requires_every_declared_rule(
    monkeypatch: pytest.MonkeyPatch, missing_rules: int
) -> None:
    stack_probe = load_stack_probe()
    expected_rule_count = stack_probe.declared_rule_count()
    calls = 0

    def declared_rule_count() -> int:
        nonlocal calls
        calls += 1
        return expected_rule_count

    monkeypatch.setattr(stack_probe, "declared_rule_count", declared_rule_count)
    monkeypatch.setattr(
        stack_probe,
        "fetch",
        lambda _: {
            "data": {
                "groups": [
                    {
                        "rules": [
                            {
                                "name": f"Alert{position}",
                                "labels": {"severity": "warning"},
                                "state": "firing",
                            }
                            for position in range(expected_rule_count - missing_rules)
                        ]
                    }
                ]
            }
        },
    )

    assert stack_probe.report_rules("http://prometheus:9090") is (missing_rules == 0)
    assert calls == 1
