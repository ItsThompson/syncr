"""``week show``, driven end to end: the credential, the two reads, and both renderings.

This is the command that proves the spine. It refreshes a stored grant, presents a bearer token,
reads the composed week, names the Areas, and answers in the format the machine implies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_cli.auth.discovery import DISCOVERY_PATH
from syncr_cli.auth.session import AUTHORIZATION_HEADER
from syncr_cli.auth.storage import KEYRING_SERVICE
from syncr_cli.exit_codes import ExitCode
from tests import payloads
from tests.fake_api import Answer, FakeApi
from tests.harness import drive

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from tests.keyrings import InMemoryKeyring

WEEK_PATH = f"/api/v1/weeks/{payloads.ISO_WEEK}"
AREAS_PATH = "/api/v1/areas"
STORED_REFRESH = "syncrr_stored"  # pragma: allowlist secret


def api_serving(api: FakeApi, *, week: dict[str, object] | None = None) -> FakeApi:
    """A fake deployment that authorizes and answers both reads."""
    api.answer("GET", DISCOVERY_PATH, Answer.json(payloads.metadata(api.base_url)))
    api.answer("POST", "/oauth/token", Answer.json(payloads.token_response()))
    api.answer("GET", WEEK_PATH, Answer.json(payloads.week() if week is None else week))
    api.answer("GET", AREAS_PATH, Answer.json(payloads.areas()))
    return api


def test_the_week_is_read_with_a_bearer_token_from_the_stored_grant(
    tmp_path: Path, in_memory_keychain: InMemoryKeyring
) -> None:
    with FakeApi() as api:
        api_serving(api)
        in_memory_keychain.stored[(KEYRING_SERVICE, api.base_url)] = STORED_REFRESH

        ran = drive(["week", "show"], base_url=api.base_url, home=tmp_path)

        presented = api.requests_to("GET", WEEK_PATH)[0].headers[AUTHORIZATION_HEADER.lower()]

    assert ran.code is ExitCode.SUCCESS
    assert presented.startswith("Bearer ")


def test_the_json_carries_the_apis_own_payload_under_the_wrapper(
    tmp_path: Path, in_memory_keychain: InMemoryKeyring
) -> None:
    # `data` is the api's object unmodified, so a member this build does not read is not lost and
    # the CLI is not a second contract to keep level with the first.
    sent = payloads.week(week_verdict=payloads.verdict(), week_operation=payloads.operation())
    with FakeApi() as api:
        api_serving(api, week=sent)
        in_memory_keychain.stored[(KEYRING_SERVICE, api.base_url)] = STORED_REFRESH

        ran = drive(["week", "show"], base_url=api.base_url, home=tmp_path)

    document = ran.document
    assert list(document) == ["ok", "data", "verdict", "operation", "problem"]
    assert document["data"] == sent
    assert document["verdict"] == sent["verdict"]
    assert document["operation"] == sent["operation"]
    assert document["problem"] is None


def test_every_duration_in_the_json_is_an_integer_count_of_minutes(
    tmp_path: Path, in_memory_keychain: InMemoryKeyring
) -> None:
    # Every member of the document, not just the strip's: `data` is the api's own object, so this is
    # the whole statement of the criterion rather than one nested part of it.
    sent = payloads.week(week_verdict=payloads.verdict(), week_operation=payloads.operation())
    with FakeApi() as api:
        api_serving(api, week=sent)
        in_memory_keychain.stored[(KEYRING_SERVICE, api.base_url)] = STORED_REFRESH

        ran = drive(["week", "show"], base_url=api.base_url, home=tmp_path)

    durations = dict(_minute_members(ran.document))
    assert durations, "expected the document to carry at least one duration"
    for name, value in durations.items():
        assert isinstance(value, int), f"{name} is {value!r}"
        assert not isinstance(value, bool), name


def _minute_members(payload: object, path: str = "") -> Iterator[tuple[str, object]]:
    """Every member of a document whose name says it is a duration in minutes."""
    if isinstance(payload, dict):
        for name, value in payload.items():
            where = f"{path}.{name}" if path else name
            if name.endswith("Minutes"):
                yield where, value
            yield from _minute_members(value, where)
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            yield from _minute_members(value, f"{path}[{index}]")


def test_the_human_ledger_and_the_json_come_from_one_read(
    tmp_path: Path, in_memory_keychain: InMemoryKeyring
) -> None:
    # The same figures in both renderings, because both are rendered from one result object.
    with FakeApi() as api:
        api_serving(api)
        in_memory_keychain.stored[(KEYRING_SERVICE, api.base_url)] = STORED_REFRESH

        as_json = drive(["week", "show", "--json"], base_url=api.base_url, home=tmp_path)
        as_human = drive(["week", "show"], base_url=api.base_url, home=tmp_path, stdout_is_tty=True)

    readings = as_json.document["data"]["readings"]
    assert f"{readings['blockCount']} blocks" in as_human.stdout
    assert "80.8h scheduled" in as_human.stdout
    assert readings["scheduledMinutes"] == 4848


def test_an_infeasible_week_exits_eight_and_still_prints_its_ledger(
    tmp_path: Path, in_memory_keychain: InMemoryKeyring
) -> None:
    # The command succeeded and the week cannot hold its commitments. That is information, not an
    # error, so `ok` is true and the code is not 1.
    with FakeApi() as api:
        api_serving(api, week=payloads.week(week_verdict=payloads.verdict()))
        in_memory_keychain.stored[(KEYRING_SERVICE, api.base_url)] = STORED_REFRESH

        ran = drive(["week", "show"], base_url=api.base_url, home=tmp_path)

    assert ran.code is ExitCode.INFEASIBLE
    assert ran.document["ok"] is True
    assert ran.document["verdict"]["feasible"] is False


def test_a_week_whose_capacity_is_sufficient_exits_zero(
    tmp_path: Path, in_memory_keychain: InMemoryKeyring
) -> None:
    with FakeApi() as api:
        api_serving(api, week=payloads.week(week_verdict=payloads.verdict(shortfalls=[])))
        in_memory_keychain.stored[(KEYRING_SERVICE, api.base_url)] = STORED_REFRESH

        ran = drive(["week", "show"], base_url=api.base_url, home=tmp_path)

    assert ran.code is ExitCode.SUCCESS


def test_the_ledger_names_areas_from_the_second_read(
    tmp_path: Path, in_memory_keychain: InMemoryKeyring
) -> None:
    week = payloads.week(
        live=payloads.plan_document(
            blocks=[
                payloads.block(
                    identifier="one",
                    start="2026-02-10T07:00:00+00:00",
                    end="2026-02-10T08:00:00+00:00",
                    title="Leetcode",
                    area_id=payloads.CAREER_ID,
                )
            ]
        )
    )
    with FakeApi() as api:
        api_serving(api, week=week)
        in_memory_keychain.stored[(KEYRING_SERVICE, api.base_url)] = STORED_REFRESH

        ran = drive(["week", "show"], base_url=api.base_url, home=tmp_path, stdout_is_tty=True)

    assert "Career" in ran.stdout
    assert str(payloads.CAREER_ID) not in ran.stdout


def test_areas_that_cannot_be_read_leave_the_column_empty_rather_than_losing_the_week(
    tmp_path: Path, in_memory_keychain: InMemoryKeyring
) -> None:
    # The week is what was asked for; a name is how a row reads. So the notice says what happened
    # and the ledger still prints.
    with FakeApi() as api:
        api_serving(api)
        api.answer(
            "GET",
            AREAS_PATH,
            Answer.problem(
                payloads.problem(problem_type="syncr:dependency-unavailable", status=503),
                status=503,
            ),
        )
        in_memory_keychain.stored[(KEYRING_SERVICE, api.base_url)] = STORED_REFRESH

        ran = drive(["week", "show"], base_url=api.base_url, home=tmp_path, stdout_is_tty=True)

    assert ran.code is ExitCode.SUCCESS
    assert "the Areas could not be read" in ran.stderr
    assert "2026-W07" in ran.stdout


def test_a_shortfall_the_domain_refuses_is_reported_in_both_formats(
    tmp_path: Path, in_memory_keychain: InMemoryKeyring
) -> None:
    # A gap of none or less is a value the domain's duration renderer refuses, and rendering is the
    # place the CLI reaches the domain. Refused at read time, so both formats agree the response is
    # unusable rather than one faulting and the other answering.
    broken = payloads.week(
        week_verdict=payloads.verdict(shortfalls=[payloads.shortfall(minutes=-5)])
    )
    with FakeApi() as api:
        api_serving(api, week=broken)
        in_memory_keychain.stored[(KEYRING_SERVICE, api.base_url)] = STORED_REFRESH

        as_json = drive(["week", "show"], base_url=api.base_url, home=tmp_path)
        as_human = drive(["week", "show"], base_url=api.base_url, home=tmp_path, stdout_is_tty=True)

    assert as_json.code is as_human.code is ExitCode.FAILURE
    assert "week.verdict.shortfalls[0].minutes" in as_json.document["problem"]["detail"]
    assert "shortfalls[0].minutes" in as_human.stdout
    assert "Traceback" not in as_human.stdout


def test_a_week_flag_beats_the_machines_current_week(
    tmp_path: Path, in_memory_keychain: InMemoryKeyring
) -> None:
    with FakeApi() as api:
        api_serving(api)
        api.answer(
            "GET",
            "/api/v1/weeks/2026-W02",
            Answer.json(payloads.week(iso_week="2026-W02")),
        )
        in_memory_keychain.stored[(KEYRING_SERVICE, api.base_url)] = STORED_REFRESH

        ran = drive(["week", "show", "--week", "2026-W02"], base_url=api.base_url, home=tmp_path)

    assert ran.code is ExitCode.SUCCESS
    assert api.requests_to("GET", "/api/v1/weeks/2026-W02")


def test_a_week_the_api_does_not_hold_exits_five(
    tmp_path: Path, in_memory_keychain: InMemoryKeyring
) -> None:
    with FakeApi() as api:
        api_serving(api)
        api.answer(
            "GET",
            WEEK_PATH,
            Answer.problem(
                payloads.problem(problem_type="syncr:not-found", status=404), status=404
            ),
        )
        in_memory_keychain.stored[(KEYRING_SERVICE, api.base_url)] = STORED_REFRESH

        ran = drive(["week", "show"], base_url=api.base_url, home=tmp_path)

    assert ran.code is ExitCode.NOT_FOUND
    assert ran.document["ok"] is False
    assert ran.document["problem"]["type"] == "syncr:not-found"
    assert ran.document["problem"]["instance"] == "correlation-1"


def test_a_response_this_build_cannot_read_says_which_member_was_wrong(
    tmp_path: Path, in_memory_keychain: InMemoryKeyring
) -> None:
    broken = payloads.week()
    del broken["readings"]["blockCount"]
    with FakeApi() as api:
        api_serving(api, week=broken)
        in_memory_keychain.stored[(KEYRING_SERVICE, api.base_url)] = STORED_REFRESH

        ran = drive(["week", "show"], base_url=api.base_url, home=tmp_path)

    assert ran.code is ExitCode.FAILURE
    assert "week.readings.blockCount" in ran.document["problem"]["detail"]


def test_an_instant_with_no_offset_is_refused_rather_than_guessed(
    tmp_path: Path, in_memory_keychain: InMemoryKeyring
) -> None:
    # A local string a reader has to guess the zone of is exactly what this wire does not carry.
    broken = payloads.week()
    broken["span"]["start"] = "2026-02-09T00:00:00"
    with FakeApi() as api:
        api_serving(api, week=broken)
        in_memory_keychain.stored[(KEYRING_SERVICE, api.base_url)] = STORED_REFRESH

        ran = drive(["week", "show"], base_url=api.base_url, home=tmp_path)

    assert ran.code is ExitCode.FAILURE
    assert "states no UTC offset" in ran.document["problem"]["detail"]


def test_a_zone_the_machine_cannot_resolve_is_reported_rather_than_faulting(
    tmp_path: Path, in_memory_keychain: InMemoryKeyring
) -> None:
    # The machine and the server can disagree about the zone database. A zone this machine has never
    # heard of is a value the CLI cannot use, and it says so instead of raising.
    broken = payloads.week(zones=dict.fromkeys(payloads.zone_by_date(), "Mars/Olympus_Mons"))
    with FakeApi() as api:
        api_serving(api, week=broken)
        in_memory_keychain.stored[(KEYRING_SERVICE, api.base_url)] = STORED_REFRESH

        ran = drive(["week", "show"], base_url=api.base_url, home=tmp_path)

    assert ran.code is ExitCode.FAILURE
    assert "Mars/Olympus_Mons" in ran.document["problem"]["detail"]


def test_a_week_missing_a_days_zone_is_refused_rather_than_guessed(
    tmp_path: Path, in_memory_keychain: InMemoryKeyring
) -> None:
    zones = payloads.zone_by_date()
    del zones["2026-02-12"]
    with FakeApi() as api:
        api_serving(api, week=payloads.week(zones=zones))
        in_memory_keychain.stored[(KEYRING_SERVICE, api.base_url)] = STORED_REFRESH

        ran = drive(["week", "show"], base_url=api.base_url, home=tmp_path)

    assert ran.code is ExitCode.FAILURE
    assert "2026-02-12" in ran.document["problem"]["detail"]
