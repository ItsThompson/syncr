"""The container's ``main``: the exit code, the exposition it writes, and the lines it emits.

Driven with the database boundary stubbed, because what is under test is the entrypoint's own
answer: a report in, an exit code and a file out. The run that produces the report has its own
suite.

**A repeated pin is not among the lines.** The api derives promotion candidates at read time from
its own pin rows, so a nightly line naming one would be a figure nobody reads. Every case here
drives a corpus the domain rule DOES find a candidate in, so the absence is measured over an input
that could have produced one, and each case reads a line the entrypoint must still emit, so a run
that logged nothing fails rather than passing an absence nobody produced.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import UUID

import pytest
import structlog

from syncr_domain.promotion import detect_repeated_pins
from syncr_domain.weeks import IsoWeek
from syncr_learning import entrypoint, metrics
from syncr_learning.entrypoint import EXIT_FAILED, EXIT_OK, main
from syncr_learning.job import run
from tests.builders import TENANT, corpus, pin
from tests.test_job import RecordingWriter, a_reader

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime
    from pathlib import Path

    from syncr_learning.job import RunReport
    from syncr_learning.storage.engine import LearningSettings

REPEATED = [pin(iso_week=IsoWeek(year=2026, week=number), hour=13) for number in (7, 8, 9)]

# The tenant whose pass completes on the night the other one's raises.
HEALTHY = UUID(int=7)


@pytest.fixture
def collected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """The textfile collector's directory, and the environment the container reads.

    The variables are set rather than defaulted, so the repository's own ``.env`` cannot decide what
    a case here measures. ``main`` configures logging itself, so the configuration is handed back
    afterwards rather than left pointing at a closed capture.
    """
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("LOG_LEVEL", "info")
    monkeypatch.setenv("TEXTFILE_COLLECTOR_DIR", str(tmp_path))
    yield tmp_path
    structlog.reset_defaults()


def stub_the_run(monkeypatch: pytest.MonkeyPatch, *, failing: bool = False) -> None:
    """Run the real nightly pass over the repeated-pin corpus where a database would be opened.

    The pass runs INSIDE ``main``, under the logging ``main`` itself configured, so every line the
    run emits is one this module can read. A report built beforehand would have logged its lines
    somewhere else, and the absence of a promotion line would then be the absence of any line.

    A failing night carries a SECOND tenant whose pass completes. A report with no completed tenant
    is one a per-candidate loop would walk zero times, so the absence of a promotion line would hold
    on that night whether or not the loop existed.
    """
    corpora = {TENANT: corpus(pins=REPEATED)}
    if failing:
        corpora[HEALTHY] = corpus(pins=REPEATED)
    reader = a_reader(corpora=corpora, fail_for=TENANT if failing else None)

    async def answered(_settings: LearningSettings, *, at: datetime) -> RunReport:
        return await run(reader, RecordingWriter(), at=at)

    monkeypatch.setattr(entrypoint, "run_once", answered)


def lines_of(captured: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in captured.splitlines() if line.startswith("{")]


def events_of(captured: str) -> list[str]:
    return [str(line.get("event")) for line in lines_of(captured)]


def test_the_fixture_is_one_a_candidate_is_raised_from() -> None:
    # The precondition every absence below rests on. Without it the cases would pass over a corpus
    # that names no repeated pin, which is the absence of a fixture rather than of a log line.
    assert len(detect_repeated_pins(REPEATED)) == 1


def test_a_clean_run_exits_zero_and_names_no_promotion_candidate(
    collected: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub_the_run(monkeypatch)

    code = main()

    emitted = events_of(capsys.readouterr().out)
    assert code == EXIT_OK
    assert "learning.tenant.fitted" in emitted, "the run's own line has to be there to read"
    assert "learning.run.finished" in emitted
    assert [one for one in emitted if "promotion" in one or "candidate" in one] == []
    assert (collected / "syncr_learning.prom").is_file()


def test_the_exposition_carries_the_run_s_own_family(
    collected: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The exposition is what a one-shot container is scraped through, so the file existing is not
    # enough: it has to hold the family the run observes.
    stub_the_run(monkeypatch)

    main()
    capsys.readouterr()

    written = (collected / "syncr_learning.prom").read_text(encoding="utf-8")
    family = next(iter(metrics.RUN_DURATION.describe())).name
    assert family in written


def test_a_failed_pass_exits_non_zero_and_reports_the_tenant(
    collected: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub_the_run(monkeypatch, failing=True)

    code = main()

    emitted = lines_of(capsys.readouterr().out)
    reported = [line for line in emitted if line["event"] == "learning.run.failed"]
    events = [str(line["event"]) for line in emitted]
    assert code == EXIT_FAILED
    assert len(reported) == 1
    assert str(TENANT) in str(reported[0]["detail"])
    assert "learning.tenant.fitted" in events, "the healthy tenant's line has to be there to read"
    assert [one for one in events if "promotion" in one or "candidate" in one] == []
    assert (collected / "syncr_learning.prom").is_file(), "a failed night is still exposed"
