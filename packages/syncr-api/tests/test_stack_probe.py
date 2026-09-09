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


@pytest.mark.parametrize(
    ("loaded_rule_count", "expected"),
    [(14, True), (13, False)],
)
def test_report_rules_requires_every_declared_rule(
    monkeypatch: pytest.MonkeyPatch, loaded_rule_count: int, expected: bool
) -> None:
    stack_probe = load_stack_probe()
    monkeypatch.setattr(stack_probe, "declared_rule_count", lambda: 14)
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
                            for position in range(loaded_rule_count)
                        ]
                    }
                ]
            }
        },
    )

    assert stack_probe.report_rules("http://prometheus:9090") is expected
