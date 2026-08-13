"""What each command does beyond answering the wrapper: its codes, its defaults, its words.

``test_every_command.py`` asserts that every command answers the wrapper and exits 0 on a happy
deployment. This is the other half: the conditions each command exists to report, and the shapes
only that command has.

Three codes are the point of this file. **8** is an infeasible verdict, which is information rather
than an error: ``block move`` is the mutation that computes one, so it is where the code reaches a
caller. **6** is a conflict, and the one a caller meets is approving a proposal that is no longer
there, in both the shapes the api answers that with: a slot an approval took, and a week that has
proposed nothing. **2** is a value that names nothing, refused in this package's words rather than
the framework's so ``--json`` still answers with a document.

**Words, not color, and never a symbol.** A pipe strips color and a pipe does not strip a word, so
every marker a row carries is asserted as a word and the whole output is asserted to hold no escape
sequence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest

from syncr_cli.api_client import API_PREFIX
from syncr_cli.auth.discovery import DISCOVERY_PATH
from syncr_cli.exit_codes import ExitCode
from tests import payloads
from tests.credentials import NO_KEYCHAIN, seed_refresh_token
from tests.fake_api import Answer, FakeApi
from tests.harness import TODAY, drive

if TYPE_CHECKING:
    from pathlib import Path

ESCAPE: Final = "\x1b"

TASKS_PATH: Final = f"{API_PREFIX}/tasks"
AREAS_PATH: Final = f"{API_PREFIX}/areas"
PINS_PATH: Final = f"{API_PREFIX}/weeks/{payloads.ISO_WEEK}/pins"
APPROVE_PATH: Final = f"{API_PREFIX}/weeks/{payloads.ISO_WEEK}/approve"
OUTCOME_PATH: Final = f"{API_PREFIX}/blocks/{payloads.BLOCK_ID}/outcome"
DAY_PATH: Final = f"{API_PREFIX}/days/{TODAY.isoformat()}"
CONFIRM_TODAY: Final = f"{API_PREFIX}/days/{TODAY.isoformat()}/confirm"

MOVED_TO: Final = "2026-02-10T07:00:00+00:00"

# The two sentences the api answers one conflict with, as fixtures rather than imports: this package
# ships nothing server-side and cannot import the api's vocabulary. What varies between them is the
# words alone, which is what makes the exit code readable off the type.
A_SLOT_AN_APPROVAL_TOOK: Final = (
    "That proposal has been replaced, so there is nothing left to approve. Nothing was changed: "
    "the week keeps the plan it holds, and reading the week again shows whatever is waiting for "
    "you now."
)
A_SLOT_NOTHING_EVER_FILLED: Final = (
    "This week is not proposing anything, so there is nothing to approve. Nothing was changed: "
    "the week keeps the plan it holds, and reading the week again shows whatever is waiting for "
    "you now."
)


def test_a_move_that_breaks_the_week_exits_eight_and_says_what_is_short(tmp_path: Path) -> None:
    # The rule an agent depends on: it learns immediately that its change broke the week, and it
    # learns it as information rather than as a failure, so `ok` is true and the code is 8.
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer(
            "POST",
            PINS_PATH,
            Answer.json(payloads.pinned(pin_verdict=payloads.verdict()), status=201),
        )

        ran = drive(
            ("block", "move", payloads.BLOCK_ID, "--to", MOVED_TO),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
            stdout_is_tty=True,
        )

    assert ran.code is ExitCode.INFEASIBLE, ran.stdout
    assert "This week cannot hold its commitments" in ran.stdout
    assert "[capacity check]" in ran.stdout
    assert "1h20m short on Career" in ran.stdout
    assert ESCAPE not in ran.stdout


def test_a_move_prints_the_solve_it_asked_for_without_exiting_by_it(tmp_path: Path) -> None:
    # The operation is reported so a caller can follow it, and it is not the outcome of the command:
    # the pin is what was asked for and the verdict is what it cost.
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer(
            "POST",
            PINS_PATH,
            Answer.json(
                payloads.pinned(
                    pin_operation=payloads.operation(
                        status="superseded", superseded_by=payloads.SUCCESSOR_ID
                    )
                ),
                status=201,
            ),
        )

        ran = drive(
            ("block", "move", payloads.BLOCK_ID, "--to", MOVED_TO),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
        )

    assert ran.code is ExitCode.SUCCESS, ran.stdout
    assert ran.document["operation"]["supersededBy"] == payloads.SUCCESSOR_ID


def test_a_move_states_the_placement_it_displaced(tmp_path: Path) -> None:
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("POST", PINS_PATH, Answer.json(payloads.pinned(), status=201))

        ran = drive(
            ("block", "move", payloads.BLOCK_ID, "--to", MOVED_TO),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
            stdout_is_tty=True,
        )

    assert "instead of 2026-02-10T05:30:00+00:00" in ran.stdout
    assert payloads.BLOCK_ID in ran.stdout


@pytest.mark.parametrize(
    "detail",
    [A_SLOT_AN_APPROVAL_TOOK, A_SLOT_NOTHING_EVER_FILLED],
    ids=["an approval took the slot", "nothing ever filled it"],
)
def test_approving_a_proposal_that_is_gone_exits_six_whichever_way_it_went(
    detail: str, tmp_path: Path
) -> None:
    """The condition code 6 exists for, in both of the shapes the api answers it with.

    Approving a proposal that is no longer there is not a usage error and not a generic failure.
    The api answers one condition with two sentences, so both reach one code and which of them
    happened is in the words alone. A caller that never saw the words could not tell a slot somebody
    else approved from a week that has proposed nothing, so the sentence is asserted where the
    caller reads it rather than the number alone.

    **Which of the two mappings carries the code is not what this asserts.** The type's row and the
    409 fallback both answer 6, so either one alone keeps this green. ``test_problems.py`` is what
    holds the type's own row.
    """
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer(
            "POST",
            APPROVE_PATH,
            Answer.problem(
                payloads.problem(problem_type="syncr:conflict", status=409, detail=detail),
                status=409,
            ),
        )

        ran = drive(("plan", "approve"), base_url=api.base_url, home=tmp_path, env=NO_KEYCHAIN)

    assert ran.code is ExitCode.CONFLICT, ran.stdout
    assert ran.document["ok"] is False
    assert ran.document["problem"]["type"] == "syncr:conflict"
    assert ran.document["problem"]["detail"] == detail


def test_an_approval_prints_both_versions_and_the_projection_it_queued(tmp_path: Path) -> None:
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("POST", APPROVE_PATH, Answer.json(payloads.approved(), status=201))

        ran = drive(
            ("plan", "approve"),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
            stdout_is_tty=True,
        )

    assert ran.code is ExitCode.SUCCESS, ran.stdout
    assert "version    8, solved against 7" in ran.stdout
    assert f"projection {payloads.PROJECTION_ID}" in ran.stdout


def test_an_approval_says_when_the_week_moved_on_while_the_proposal_waited(
    tmp_path: Path,
) -> None:
    # The pair of versions is what makes that visible rather than something a caller has to infer,
    # and the divergence is a gap wider than the approval's own bump.
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer(
            "POST",
            APPROVE_PATH,
            Answer.json(payloads.approved(input_version=12, solved_against_version=7), status=201),
        )

        ran = drive(
            ("plan", "approve"),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
            stdout_is_tty=True,
        )

    assert "the week moved on while this proposal waited" in ran.stdout


def test_day_confirm_defaults_to_this_machines_today(tmp_path: Path) -> None:
    # The date a person answers for is almost always the one they have just lived, and today is the
    # machine's own local date rather than the server's.
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("POST", CONFIRM_TODAY, Answer.json(payloads.day(on=TODAY)))

        ran = drive(("day", "confirm"), base_url=api.base_url, home=tmp_path, env=NO_KEYCHAIN)

    assert ran.code is ExitCode.SUCCESS, ran.stdout
    assert api.requests_to("POST", CONFIRM_TODAY)


def test_a_confirmed_day_reads_its_settled_ledger_back_in_words(tmp_path: Path) -> None:
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer(
            "POST",
            CONFIRM_TODAY,
            Answer.json(
                payloads.day(
                    on=TODAY,
                    confirmed_at="2026-02-10T23:00:00+00:00",
                    behind=[payloads.ledger_row(recorded=payloads.outcome(state="completed"))],
                )
            ),
        )

        ran = drive(
            ("day", "confirm"),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
            stdout_is_tty=True,
        )

    assert "confirmed" in ran.stdout
    assert "Career" in ran.stdout
    assert "completed" in ran.stdout
    assert "ahead" in ran.stdout
    assert ESCAPE not in ran.stdout


def test_a_partial_recording_names_the_minutes_it_really_took(tmp_path: Path) -> None:
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer(
            "PUT", OUTCOME_PATH, Answer.json(payloads.outcome(state="partial", actual_minutes=45))
        )

        ran = drive(
            ("block", "partial", payloads.BLOCK_ID, "--minutes", "45"),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
            stdout_is_tty=True,
        )

    assert "recorded   partial 45m" in ran.stdout
    body = api.requests_to("PUT", OUTCOME_PATH)[0].body.decode()
    assert '"actualMinutes": 45' in body or '"actualMinutes":45' in body
    assert payloads.ISO_WEEK in body


def test_a_completion_sends_no_minute_count_at_all(tmp_path: Path) -> None:
    # The api refuses a body carrying a figure its state cannot read, so a client that sent a null
    # would be sending a value the state has no use for.
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("PUT", OUTCOME_PATH, Answer.json(payloads.outcome()))

        drive(
            ("block", "done", payloads.BLOCK_ID),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
        )

    assert "actualMinutes" not in api.requests_to("PUT", OUTCOME_PATH)[0].body.decode()


def test_a_recording_says_the_day_is_still_unconfirmed(tmp_path: Path) -> None:
    # Recording an outcome does not confirm the day, and the day stays out of reviews and out of
    # learning until it is. Saying so is what stops a caller thinking it answered for the day.
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("PUT", OUTCOME_PATH, Answer.json(payloads.outcome(state="skipped")))

        ran = drive(
            ("block", "skip", payloads.BLOCK_ID),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
            stdout_is_tty=True,
        )

    assert "unconfirmed, so it is excluded from reviews and from learning" in ran.stdout


def test_a_capture_sends_only_what_the_caller_stated(tmp_path: Path) -> None:
    # Every other field has a default the api owns, and a value this client filled in would be a
    # second statement of a rule that has an owner.
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("POST", TASKS_PATH, Answer.json(payloads.task(), status=201))

        drive(
            ("task", "add", "Leetcode", "--area", str(payloads.CAREER_ID)),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
        )

    sent = api.requests_to("POST", TASKS_PATH)[0].body.decode()
    assert '"areaId"' in sent
    assert '"title"' in sent
    for absent in ("estimateMinutes", "minChunkMinutes", "priority", "deadline", "splittable"):
        assert absent not in sent


def test_a_capture_sends_every_field_the_caller_did_state(tmp_path: Path) -> None:
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("POST", TASKS_PATH, Answer.json(payloads.task(), status=201))

        ran = drive(
            (
                "task",
                "add",
                "Leetcode",
                "--area",
                str(payloads.CAREER_ID),
                "--estimate",
                "180",
                "--min-chunk",
                "45",
                "--priority",
                "high",
                "--deadline",
                "2026-02-13T09:00:00+00:00",
                "--atomic",
            ),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
        )

    assert ran.code is ExitCode.SUCCESS, ran.stdout
    sent = api.requests_to("POST", TASKS_PATH)[0].body.decode()
    for stated in ("estimateMinutes", "minChunkMinutes", "priority", "deadline"):
        assert stated in sent
    assert "false" in sent


def test_a_deadline_without_an_offset_is_a_usage_error_rather_than_a_guess(
    tmp_path: Path,
) -> None:
    # A local wall time is what this wire does not carry. A caller in a zone ahead of the server's
    # would otherwise state a deadline a day early and be told nothing.
    with FakeApi() as api:
        _serving(api, tmp_path)

        ran = drive(
            (
                "task",
                "add",
                "Leetcode",
                "--area",
                str(payloads.CAREER_ID),
                "--deadline",
                "2026-02-13T09:00",
            ),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
        )

    assert ran.code is ExitCode.USAGE, ran.stdout
    assert ran.document["problem"]["type"] == "syncr:cli-usage"
    assert "states no UTC offset" in ran.document["problem"]["detail"]
    assert api.requests_to("POST", TASKS_PATH) == []


def test_a_move_to_an_instant_without_an_offset_is_refused_the_same_way(tmp_path: Path) -> None:
    with FakeApi() as api:
        _serving(api, tmp_path)

        ran = drive(
            ("block", "move", payloads.BLOCK_ID, "--to", "2026-02-10T07:00"),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
        )

    assert ran.code is ExitCode.USAGE, ran.stdout
    assert api.requests_to("POST", PINS_PATH) == []


def test_a_date_that_names_nothing_is_a_usage_error(tmp_path: Path) -> None:
    with FakeApi() as api:
        _serving(api, tmp_path)

        ran = drive(("day", "confirm", "2026-02-30"), base_url=api.base_url, home=tmp_path)

    assert ran.code is ExitCode.USAGE, ran.stdout
    assert "not an ISO date" in ran.document["problem"]["detail"]


def test_the_backlog_prints_the_at_risk_count_the_server_determined(tmp_path: Path) -> None:
    # Read, never computed: a client that compared a deadline against a capacity of its own would
    # put a task at risk on one surface and fine on another.
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("GET", AREAS_PATH, Answer.json(payloads.areas()))
        api.answer(
            "GET",
            TASKS_PATH,
            Answer.json(payloads.backlog(open_count=9, at_risk_count=2)),
        )

        ran = drive(
            ("backlog", "list"),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
            stdout_is_tty=True,
        )

    assert "9 open" in ran.stdout
    assert "2 at risk" in ran.stdout
    assert "Career" in ran.stdout
    assert ESCAPE not in ran.stdout


def test_the_backlog_marks_a_task_the_verdict_named_and_leaves_the_rest_unmarked(
    tmp_path: Path,
) -> None:
    # The marking, in words, from the server's own determination. Both rows in one read, so a
    # renderer that marked everything or nothing would fail: what is asserted is the discrimination.
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("GET", AREAS_PATH, Answer.json(payloads.areas()))
        api.answer(
            "GET",
            TASKS_PATH,
            Answer.json(
                payloads.backlog(
                    tasks=[
                        payloads.task(title="Owed", at_risk=True),
                        payloads.task(identifier="other", title="Fine", at_risk=False),
                    ],
                    open_count=2,
                    at_risk_count=1,
                )
            ),
        )

        ran = drive(
            ("backlog", "list"),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
            stdout_is_tty=True,
        )

    marked = [line for line in ran.lines if "at risk" in line]
    assert len(marked) == 2, ran.stdout
    assert "1 at risk" in marked[0]
    assert "Owed" in marked[1]


def test_a_backlog_without_the_at_risk_field_at_all_still_prints(tmp_path: Path) -> None:
    # The smaller claim. A build whose probe does not yet mark a task answers without the member,
    # and a reader that required it would refuse a backlog rather than printing one.
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("GET", AREAS_PATH, Answer.json(payloads.areas()))
        api.answer("GET", TASKS_PATH, Answer.json(payloads.backlog()))

        ran = drive(
            ("backlog", "list"),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
            stdout_is_tty=True,
        )

    assert ran.code is ExitCode.SUCCESS, ran.stdout
    assert "atRisk" not in api.requests_to("GET", TASKS_PATH)[0].body.decode()
    assert [line for line in ran.lines if "at risk" in line] == [
        line for line in ran.lines if "0 at risk" in line
    ]


def test_the_backlog_asks_for_the_open_work_and_task_list_asks_for_every_status(
    tmp_path: Path,
) -> None:
    # One read and two questions. The backlog is what is still owed; `task list` answers what tasks
    # there are, so it imposes nothing.
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("GET", AREAS_PATH, Answer.json(payloads.areas()))
        api.answer("GET", TASKS_PATH, Answer.json(payloads.backlog()))

        drive(("backlog", "list"), base_url=api.base_url, home=tmp_path, env=NO_KEYCHAIN)
        drive(("task", "list"), base_url=api.base_url, home=tmp_path, env=NO_KEYCHAIN)

    asked = [one.query for one in api.requests_to("GET", TASKS_PATH)]
    assert asked == [{"status": ["open"]}, {}]


def test_the_at_risk_filter_reaches_the_api_rather_than_narrowing_the_answer(
    tmp_path: Path,
) -> None:
    """The narrowing is the server's, because the determination is.

    Asserted from both ends, because either alone leaves the other half free. The REQUEST carries
    the parameter the route serves, spelled the way the route spells it, so a client that answered
    the filter out of an unfiltered read would send nothing. And the ANSWER holds one marked row
    and one unmarked one whatever is asked for, so a client that narrowed what came back as well
    would print one row beside a header the server computed over two.
    """
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("GET", AREAS_PATH, Answer.json(payloads.areas()))
        api.answer(
            "GET",
            TASKS_PATH,
            Answer.json(
                payloads.backlog(
                    tasks=[
                        payloads.task(title="Owed", at_risk=True),
                        payloads.task(identifier="other", title="Fine", at_risk=False),
                    ],
                    open_count=2,
                    at_risk_count=1,
                )
            ),
        )

        marked = drive(
            ("backlog", "list", "--at-risk"),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
        )
        drive(("task", "list", "--at-risk"), base_url=api.base_url, home=tmp_path, env=NO_KEYCHAIN)

    asked = [one.query for one in api.requests_to("GET", TASKS_PATH)]
    assert asked == [{"status": ["open"], "atRisk": ["true"]}, {"atRisk": ["true"]}]
    assert marked.code is ExitCode.SUCCESS, marked.stdout
    assert [task["title"] for task in marked.document["data"]["tasks"]] == ["Owed", "Fine"]


def test_the_backlog_sends_no_at_risk_parameter_when_the_flag_is_absent(tmp_path: Path) -> None:
    """An unstated filter is an omitted parameter, not `atRisk=false`, which asks a question."""
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("GET", AREAS_PATH, Answer.json(payloads.areas()))
        api.answer("GET", TASKS_PATH, Answer.json(payloads.backlog()))

        drive(("backlog", "list"), base_url=api.base_url, home=tmp_path, env=NO_KEYCHAIN)

    assert api.requests_to("GET", TASKS_PATH)[0].query == {"status": ["open"]}


def test_an_empty_backlog_says_so_rather_than_printing_nothing(tmp_path: Path) -> None:
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("GET", AREAS_PATH, Answer.json(payloads.areas()))
        api.answer("GET", TASKS_PATH, Answer.json(payloads.backlog(tasks=[], open_count=0)))

        ran = drive(
            ("backlog", "list"),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
            stdout_is_tty=True,
        )

    assert "nothing captured" in ran.stdout


def test_plan_show_with_a_date_reads_the_day_and_without_one_reads_the_week(
    tmp_path: Path,
) -> None:
    week = f"{API_PREFIX}/weeks/{payloads.ISO_WEEK}"
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("GET", AREAS_PATH, Answer.json(payloads.areas()))
        api.answer("GET", week, Answer.json(payloads.week()))
        api.answer("GET", DAY_PATH, Answer.json(payloads.day(on=TODAY)))

        by_week = drive(("plan", "show"), base_url=api.base_url, home=tmp_path, env=NO_KEYCHAIN)
        by_date = drive(
            ("plan", "show", "--date", TODAY.isoformat()),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
        )

    assert by_week.document["data"]["isoWeek"] == payloads.ISO_WEEK
    assert by_date.document["data"]["date"] == TODAY.isoformat()


def test_a_backlog_read_survives_areas_it_could_not_name(tmp_path: Path) -> None:
    # The Area read is how a row reads, not what was asked for. A refused one leaves the column at
    # `--` with a notice on stderr, and the backlog itself is unaffected.
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("GET", TASKS_PATH, Answer.json(payloads.backlog()))
        api.answer(
            "GET",
            AREAS_PATH,
            Answer.problem(
                payloads.problem(problem_type="syncr:internal-error", status=500), status=500
            ),
        )

        ran = drive(
            ("backlog", "list"),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
            stdout_is_tty=True,
        )

    assert ran.code is ExitCode.SUCCESS, ran.stdout
    assert "--" in ran.stdout
    assert "the Areas could not be read" in ran.stderr


def test_a_read_that_times_out_says_nothing_was_changed(tmp_path: Path) -> None:
    # A read that never answered changed nothing and may say so. The safe half of the pair below.
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("GET", TASKS_PATH, Answer.raw(b"", 200))

        ran = drive(
            ("task", "list"),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
        )

    detail = ran.document["problem"]["detail"]
    assert "Nothing was changed." in detail
    assert "cannot be told from here" not in detail


def test_a_mutation_whose_answer_cannot_be_read_does_not_claim_nothing_changed(
    tmp_path: Path,
) -> None:
    """The rule this surface cannot afford to get wrong, in the direction that is false by default.

    A capture that answered 201 with a body this build cannot read HAS created a task. Saying
    "nothing was changed" beside a task that now exists is a lie to the one reader that acts on the
    sentence, so the message states that the outcome cannot be told from here and that retrying the
    same command is safe, which is true because the key makes it so.
    """
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("POST", TASKS_PATH, Answer.raw(b"created, but not as JSON", 201))

        ran = drive(
            ("task", "add", "Leetcode", "--area", str(payloads.CAREER_ID)),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
        )

    detail = ran.document["problem"]["detail"]
    assert ran.code is ExitCode.FAILURE, ran.stdout
    assert "Nothing was changed." not in detail
    assert "cannot be told from here" in detail
    assert "Idempotency-Key" in detail


def test_a_mutation_whose_response_is_missing_a_member_says_the_same(tmp_path: Path) -> None:
    # The other way a mutation's answer is unreadable: valid JSON missing a member this build reads.
    # It reaches the wire readers rather than the transport, and they cannot know the method either.
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("POST", TASKS_PATH, Answer.json({"id": "only-an-id"}, status=201))

        ran = drive(
            ("task", "add", "Leetcode", "--area", str(payloads.CAREER_ID)),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
        )

    detail = ran.document["problem"]["detail"]
    assert "Nothing was changed." not in detail
    assert "cannot be told from here" in detail


def _serving(api: FakeApi, home: Path) -> None:
    api.answer("GET", DISCOVERY_PATH, Answer.json(payloads.metadata(api.base_url)))
    api.answer("POST", "/oauth/token", Answer.json(payloads.token_response()))
    seed_refresh_token(home, api.base_url)
