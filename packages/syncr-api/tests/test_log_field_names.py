"""What may appear in a log line, derived from every log call the tree actually makes.

Ticket 1 built the redaction rule and asserted it over the field names that existed then. A rule
asserted over a fixed list degrades silently as new code arrives: the next feature adds a field, the
list is not extended, and the guard passes while the leak ships. That is the defect class this file
closes, so the inventory is READ FROM THE SOURCE rather than written down.

Every keyword a log call passes is collected by walking the three trees as text. Two rules are then
stated over whatever that walk finds:

- A field whose NAME reads as user content must be one the redactor eats. ``block_title`` is covered
  by the suffix rule and ``titles`` would not be, so a plural or a compound that slipped past the
  rule fails here rather than reaching disk.
- No log call passes a whole domain object. ``block=block`` would render whatever ``__repr__`` says,
  which for a block is its title, and the redactor cannot inspect a value it has no key for.

The second half of this file is the other side of the same subject: what is deliberately NOT
instrumented. There is no analytics vendor, no session recording, no external error reporting, and
NO DISTRIBUTED TRACING. Tracing's absence is a decision rather than an omission, because its value
scales with the number of network hops between services and syncr has approximately one; a
correlation id on every structured line answers the same questions with no infrastructure. Asserted
rather than only stated, so a dependency that arrived with one of them fails a gate.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

import syncr_api
from syncr_common.logging import is_sensitive_key

if TYPE_CHECKING:
    from collections.abc import Iterator

# The methods a bound logger offers. A call to any of them carries log fields as keywords.
LOG_LEVELS: Final = frozenset(
    {"debug", "info", "warning", "warn", "error", "critical", "exception"}
)

# Keywords every log call may carry that are not fields at all: structlog's own, and the exception
# the error path attaches.
NOT_A_FIELD: Final = frozenset({"exc_info", "stack_info", "stacklevel"})

# Words that make a field name read as the user's own words rather than as an identifier. A name
# containing one of these must be a name the redactor eats, whatever shape it takes around it.
CONTENT_WORDS: Final = ("title", "location", "summary", "description", "notes", "label")

# Packages whose presence would mean something is instrumented that should not be. Tracing is the
# deliberate omission; the rest would send plan content to a third party.
FORBIDDEN_DEPENDENCIES: Final = (
    "opentelemetry",
    "opentracing",
    "jaeger",
    "zipkin",
    "ddtrace",
    "sentry-sdk",
    "sentry_sdk",
    "elastic-apm",
    "newrelic",
    "posthog",
    "mixpanel",
    "segment-analytics",
    "amplitude",
)


def repo_root() -> Path:
    return Path(syncr_api.__file__).resolve().parents[4]


def source_trees() -> list[Path]:
    """Every tree that emits a log line: the api, the offline learning job, and the CLI."""
    root = repo_root()
    return [
        root / "packages" / "syncr-api" / "src" / "syncr_api",
        root / "packages" / "syncr-common" / "src" / "syncr_common",
        root / "packages" / "syncr-learning" / "src" / "syncr_learning",
        root / "cli" / "src" / "syncr_cli",
    ]


def _is_a_log_call(call: ast.Call) -> bool:
    """Whether this call is a log emission, judged by the method name and the receiver."""
    if not isinstance(call.func, ast.Attribute) or call.func.attr not in LOG_LEVELS:
        return False
    receiver = call.func.value
    # `_log.info(...)`, `self._log.info(...)`, `log.info(...)`, `get_logger("x").info(...)`.
    if isinstance(receiver, ast.Name):
        return "log" in receiver.id.lower()
    if isinstance(receiver, ast.Attribute):
        return "log" in receiver.attr.lower()
    if isinstance(receiver, ast.Call):
        return isinstance(receiver.func, ast.Name) and "logger" in receiver.func.id.lower()
    return False


def log_calls() -> Iterator[tuple[Path, ast.Call]]:
    """Every log emission in every tree, with the file it came from."""
    for tree in source_trees():
        for path in sorted(tree.rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Call) and _is_a_log_call(node):
                    yield path, node


def log_field_names() -> set[str]:
    """Every keyword name any log call in the tree passes."""
    return {
        keyword.arg
        for _path, call in log_calls()
        for keyword in call.keywords
        if keyword.arg is not None and keyword.arg not in NOT_A_FIELD
    }


def content_shaped(names: set[str]) -> set[str]:
    """The names that read as the user's own words rather than as an identifier."""
    return {name for name in names if any(word in name.lower() for word in CONTENT_WORDS)}


class TestTheInventoryItself:
    """Positive controls. A walk that found nothing would make every rule below vacuous."""

    def test_it_finds_the_log_calls_the_tree_makes(self) -> None:
        assert len(list(log_calls())) > 100

    def test_it_finds_the_fields_those_calls_carry(self) -> None:
        names = log_field_names()

        assert len(names) > 60
        # Three the tree certainly passes, one per tree that emits.
        assert "tenant_id" in names
        assert "iso_week" in names

    def test_it_recognises_a_content_shaped_name(self) -> None:
        assert content_shaped({"block_title", "titles", "period_label", "tenant_id"}) == {
            "block_title",
            "titles",
            "period_label",
        }


class TestEveryFieldTheTreeLogs:
    def test_no_content_shaped_field_escapes_the_redactor(self) -> None:
        """The rule ticket 1 stated, applied to every field name introduced since.

        A field the redactor does not eat is a field whose value reaches disk. For a name carrying
        `title`, `location`, `label`, `summary`, `description` or `notes`, that value is the user's
        own words: a line carrying `Kontron Placement Interview` discloses a job search to anyone
        with log access, and a line carrying an anchor location discloses where the user physically
        is at a given hour, for weeks ahead.
        """
        escaped = {name for name in content_shaped(log_field_names()) if not is_sensitive_key(name)}

        assert escaped == set()

    def test_every_field_name_is_a_name_and_not_an_expression(self) -> None:
        """A log call splatting a mapping hides its own field names from this walk.

        `**fields` is legitimate where the mapping is built by a tally's `as_log_fields`, which
        names its keys deliberately. What is not legitimate is splatting a domain object's
        `__dict__`, which would carry whatever fields that object holds under the names it uses.
        """
        splatted = [
            (path.name, call.lineno)
            for path, call in log_calls()
            for keyword in call.keywords
            if keyword.arg is None and not isinstance(keyword.value, ast.Call | ast.Dict | ast.Name)
        ]

        assert splatted == []


class TestWhatIsDeliberatelyNotInstrumented:
    def test_no_tracing_and_no_analytics_dependency_exists(self) -> None:
        """Tracing's value scales with network hops, and syncr has approximately one.

        A correlation id on every structured log line answers the same questions without the
        infrastructure. The rest of the list would send plan content to a third party, and there
        is no third party receiving anything at all.
        """
        manifests = [*repo_root().glob("**/pyproject.toml"), repo_root() / "uv.lock"]
        declared = "\n".join(
            path.read_text() for path in manifests if path.exists() and ".venv" not in str(path)
        )

        for forbidden in FORBIDDEN_DEPENDENCIES:
            assert forbidden not in declared.lower()

    def test_no_frontend_analytics_dependency_exists(self) -> None:
        """No analytics vendor, no session recording, and no third party receiving anything."""
        manifest = repo_root() / "frontend" / "package.json"

        declared = manifest.read_text().lower()

        for forbidden in (*FORBIDDEN_DEPENDENCIES, "hotjar", "fullstory", "logrocket", "datadog"):
            assert forbidden not in declared

    @pytest.mark.parametrize(
        "instrumented",
        ["syncr_trace", "syncr_span", "syncr_block_title", "syncr_analytics"],
    )
    def test_no_family_names_a_thing_that_should_not_be_measured(self, instrumented: str) -> None:
        """No per-block content, no client-side analytics, and no spans.

        Stated over the family NAMES a source declares rather than over a registry, so a family
        declared on a registry of its own is covered too.
        """
        declares = re.compile(rf'"{instrumented}[a-z_]*"')

        for tree in source_trees():
            for path in tree.rglob("*.py"):
                assert not declares.search(path.read_text()), f"{path} declares {instrumented}"
