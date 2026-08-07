"""The payloads a fake API answers with, built from the shapes the real api emits.

Factories rather than literals in each test, so a shape change is one edit and every test states
only what it is about. Each default is a value the api could really send: camelCase members,
RFC 3339 instants with an explicit offset, and every duration an integer minute count.

The week payload is the one from section 17's ledger, dates and all, so a rendering assertion is
against the documented shape rather than against whatever this module happened to invent.
"""

from __future__ import annotations

import json
from base64 import urlsafe_b64encode
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

ISO_WEEK = "2026-W07"
ZONE = "Europe/London"

FITNESS_ID = UUID("11111111-1111-4111-8111-111111111111")
CAREER_ID = UUID("22222222-2222-4222-8222-222222222222")
TRANSIT_ID = UUID("33333333-3333-4333-8333-333333333333")

TENANT_ID = "44444444-4444-4444-8444-444444444444"
USER_ID = "55555555-5555-4555-8555-555555555555"
OPERATION_ID = "66666666-6666-4666-8666-666666666666"
SUCCESSOR_ID = "77777777-7777-4777-8777-777777777777"


def zone_by_date(zone: str = ZONE, iso_week: str = ISO_WEEK) -> dict[str, str]:
    """One zone on each of the week's seven dates, keyed as the api keys them."""
    return {on.isoformat(): zone for on in _dates(iso_week)}


def week_span(iso_week: str = ISO_WEEK, zone: str = ZONE) -> dict[str, str]:
    """The week's real span: its own Monday midnight to the next, resolved in ``zone``."""
    dates = _dates(iso_week)
    resolved = ZoneInfo(zone)
    opens = datetime.combine(dates[0], time(0, 0), tzinfo=resolved)
    closes = datetime.combine(dates[-1] + timedelta(days=1), time(0, 0), tzinfo=resolved)
    return span(opens.astimezone(UTC).isoformat(), closes.astimezone(UTC).isoformat())


def _dates(iso_week: str) -> list[date]:
    year, week = int(iso_week[:4]), int(iso_week[6:])
    monday = date.fromisocalendar(year, week, 1)
    return [monday + timedelta(days=offset) for offset in range(7)]


def span(start: str, end: str) -> dict[str, str]:
    return {"start": start, "end": end}


def block(
    *,
    identifier: str,
    start: str,
    end: str,
    title: str,
    origin: str = "task",
    area_id: UUID | None = CAREER_ID,
    pinned: bool = False,
) -> dict[str, Any]:
    """One block, with the members the ledger reads and nothing it does not."""
    return {
        "id": identifier,
        "interval": span(start, end),
        "binding": {
            "kind": "task",
            "entityId": str(CAREER_ID),
            "occurrenceKey": "2026-02-10",
            "splitIndex": None,
        },
        "origin": origin,
        "title": title,
        "reason": {"clauses": []},
        "areaId": None if area_id is None else str(area_id),
        "pinned": pinned,
        "supersededPlacement": None,
        "objectiveDelta": None,
        "splitCount": None,
    }


def forbidden_window(*, start: str, end: str, label: str) -> dict[str, Any]:
    return {
        "interval": span(start, end),
        "kind": "recovery",
        "scope": "all",
        "forbiddenAreaIds": [],
        "label": label,
        "anchorId": str(CAREER_ID),
    }


def plan_document(
    *, blocks: list[dict[str, Any]] | None = None, windows: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "isoWeek": ISO_WEEK,
        "zoneByDate": zone_by_date(),
        "blocks": [] if blocks is None else blocks,
        "forbiddenWindows": [] if windows is None else windows,
        "emptySlots": [],
        "adjustments": [],
    }


def readings(
    *,
    block_count: int = 91,
    scheduled_minutes: int = 4848,
    discretionary_minutes: int = 3126,
    unallocated_minutes: int = 1104,
    unconfirmed_days: int = 3,
    plan_currency: str = "current",
) -> dict[str, Any]:
    return {
        "scheduledMinutes": scheduled_minutes,
        "discretionaryMinutes": discretionary_minutes,
        "unallocatedMinutes": unallocated_minutes,
        "oversubscriptionMinutes": 0,
        "unconfirmedDays": unconfirmed_days,
        "offPlanMinutes": 0,
        "blockCount": block_count,
        "planCurrency": plan_currency,
    }


def shortfall(
    *,
    minutes: int = 80,
    against: list[str] | None = None,
    honoring: list[str] | None = None,
    deadline: str | None = "2026-02-13T09:00:00+00:00",
) -> dict[str, Any]:
    return {
        "kind": "deadline_capacity",
        "minutes": minutes,
        "against": ["Career"] if against is None else against,
        "honoring": ["the Fitness floor of 5h"] if honoring is None else honoring,
        "deadline": deadline,
        "areaId": str(CAREER_ID),
    }


def verdict(
    *,
    feasible: bool = False,
    provenance: str = "probe",
    shortfalls: list[dict[str, Any]] | None = None,
    tradeoffs: int = 4,
) -> dict[str, Any]:
    return {
        "feasible": feasible,
        "provenance": provenance,
        "computedAt": "2026-02-09T08:00:00+00:00",
        "inputVersion": 7,
        "discretionaryMinutes": 3126,
        "shortfalls": [shortfall()] if shortfalls is None else shortfalls,
        "tradeoffs": [
            {
                "kind": "reduce_sleep",
                "label": f"Tradeoff {position}",
                "targetId": str(CAREER_ID),
                "deltaMinutes": 20,
            }
            for position in range(tradeoffs)
        ],
    }


def operation(
    *,
    status: str = "pending",
    kind: str = "solve",
    identifier: str = OPERATION_ID,
    superseded_by: str | None = None,
    error: dict[str, str] | None = None,
    attempt: int = 1,
    statement: str = "This solve is queued. The previous plan is unchanged.",
) -> dict[str, Any]:
    return {
        "id": identifier,
        "kind": kind,
        "status": status,
        "target": {"isoWeek": ISO_WEEK, "sourceId": None},
        "inputVersion": 7,
        "scheduledFor": "2026-02-09T08:00:00+00:00",
        "startedAt": None,
        "finishedAt": None,
        "resultRevisionId": None,
        "supersededBy": superseded_by,
        "attempt": attempt,
        "error": error,
        "statement": statement,
    }


def week(
    *,
    live: dict[str, Any] | None = None,
    week_readings: dict[str, Any] | None = None,
    week_verdict: dict[str, Any] | None = None,
    week_operation: dict[str, Any] | None = None,
    zones: dict[str, str] | None = None,
    conflicts: list[dict[str, Any]] | None = None,
    proposal: dict[str, Any] | None = None,
    iso_week: str = ISO_WEEK,
) -> dict[str, Any]:
    """The composed week view, with a plan unless a test says otherwise."""
    document = plan_document() if live is None else live
    return {
        "isoWeek": iso_week,
        "span": week_span(iso_week),
        "zoneByDate": zone_by_date(iso_week=iso_week) if zones is None else zones,
        "live": document,
        "emptyReason": None,
        "emptyWeek": None,
        "proposal": proposal,
        "candidateAdjustment": None,
        "adjustments": [],
        "pins": [],
        "conflicts": [] if conflicts is None else conflicts,
        "verdict": week_verdict,
        "offPlan": [],
        "operation": week_operation,
        "inputVersion": 7,
        "readings": readings() if week_readings is None else week_readings,
    }


def empty_week(*, statement: str = "This week is beyond the projection horizon.") -> dict[str, Any]:
    """A week the plan-horizon maintainer has not reached, which is not an error."""
    view = week()
    view.update(
        {
            "live": None,
            "readings": None,
            "verdict": None,
            "emptyReason": "outside_horizon",
            "emptyWeek": {
                "statement": statement,
                "missingInputs": [],
                "horizonDays": 28,
                "horizonThrough": "2026-02-08",
                "coversThisWeek": False,
            },
        }
    )
    return view


def areas() -> dict[str, Any]:
    """Three Areas, named as the ledger prints them."""
    return {
        "areas": [
            _area(FITNESS_ID, "Fitness", 0),
            _area(CAREER_ID, "Career", 1),
            _area(TRANSIT_ID, "Transit", 2),
        ],
        "ramp": {"pigmentCount": 12, "pigmentsInUse": 3, "sharedSteps": [], "statement": None},
    }


def _area(identifier: UUID, name: str, pigment: int) -> dict[str, Any]:
    return {
        "id": str(identifier),
        "parentId": None,
        "name": name,
        "pigmentIndex": pigment,
        "targetShare": 10.0,
        "floorHours": 5.0,
        "projectCount": 0,
    }


def problem(
    *,
    problem_type: str,
    status: int,
    title: str = "Refused",
    detail: str = "The API refused this. Nothing was changed.",
    instance: str | None = "correlation-1",
) -> dict[str, Any]:
    return {
        "type": problem_type,
        "title": title,
        "status": status,
        "detail": detail,
        "instance": instance,
    }


TASK_ID = "88888888-8888-4888-8888-888888888888"
REVISION_ID = "99999999-9999-4999-8999-999999999999"
PIN_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
PROJECTION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

BLOCK_ID = "blk-career-leetcode-0"
TUESDAY = date(2026, 2, 10)


def task(
    *,
    identifier: str = TASK_ID,
    title: str = "Leetcode",
    area_id: UUID = CAREER_ID,
    estimate_minutes: int = 150,
    recorded_minutes: int = 0,
    remaining_minutes: int = 150,
    deadline: str | None = None,
    priority: str = "normal",
    status: str = "open",
    eligible: bool = True,
    at_risk: bool | None = None,
) -> dict[str, Any]:
    """One task, with the members the backlog reads and nothing it does not.

    ``at_risk`` is ``None`` by default, which omits the member: that is the shape a build without
    the probe answers with, and the reader treats an absent mark as false.
    """
    row = {
        "id": identifier,
        "areaId": str(area_id),
        "projectId": None,
        "title": title,
        "estimateMinutes": estimate_minutes,
        "recordedMinutes": recorded_minutes,
        "remainingMinutes": remaining_minutes,
        "deadline": deadline,
        "priority": priority,
        "minChunkMinutes": 30,
        "splittable": True,
        "status": status,
        "completedAt": None,
        "eligibleForSolving": eligible,
    }
    if at_risk is not None:
        row["atRisk"] = at_risk
    return row


def backlog(
    *,
    tasks: list[dict[str, Any]] | None = None,
    open_count: int = 1,
    at_risk_count: int = 0,
) -> dict[str, Any]:
    """The backlog: its header counts, and the tasks a filter selected."""
    return {
        "header": {"openCount": open_count, "atRiskCount": at_risk_count},
        "tasks": [task()] if tasks is None else tasks,
    }


def outcome(
    *,
    block_id: str = BLOCK_ID,
    state: str = "completed",
    actual_minutes: int | None = None,
    confirmed_at: str | None = None,
) -> dict[str, Any]:
    """What the log holds for one block, as a recording answers with it."""
    return {
        "blockId": block_id,
        "state": state,
        "actualMinutes": actual_minutes,
        "actualInterval": None,
        "occurredAt": "2026-02-10T07:00:00+00:00",
        "confirmedAt": confirmed_at,
    }


def ledger_row(
    *,
    block_id: str = BLOCK_ID,
    start: str = "2026-02-10T07:00:00+00:00",
    end: str = "2026-02-10T09:30:00+00:00",
    duration_minutes: int = 150,
    area_name: str | None = "Career",
    title: str = "Leetcode",
    origin: str = "task",
    recorded: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One row of a day, as the Today ledger sends it."""
    return {
        "blockId": block_id,
        "interval": span(start, end),
        "durationMinutes": duration_minutes,
        "areaId": str(CAREER_ID),
        "areaName": area_name,
        "title": title,
        "origin": origin,
        "outcome": recorded,
    }


def day(
    *,
    on: date = TUESDAY,
    behind: list[dict[str, Any]] | None = None,
    ahead: list[dict[str, Any]] | None = None,
    confirmed_at: str | None = None,
    presumed_count: int = 1,
    unconfirmed_days: int = 3,
) -> dict[str, Any]:
    """One date's ledger, with a row behind and a row ahead unless a test says otherwise."""
    settled = [ledger_row()] if behind is None else behind
    coming = (
        [
            ledger_row(
                block_id="blk-fitness-gym-0",
                start="2026-02-10T18:00:00+00:00",
                end="2026-02-10T19:00:00+00:00",
                duration_minutes=60,
                area_name="Fitness",
                title="Gym",
                origin="habit",
            )
        ]
        if ahead is None
        else ahead
    )
    return {
        "date": on.isoformat(),
        "zone": ZONE,
        "span": span(
            f"{on.isoformat()}T00:00:00+00:00",
            f"{(on + timedelta(days=1)).isoformat()}T00:00:00+00:00",
        ),
        "blockCount": len(settled) + len(coming),
        "presumedCount": presumed_count,
        "confirmedAt": confirmed_at,
        "unconfirmedDays": unconfirmed_days,
        "behind": settled,
        "ahead": coming,
    }


def pinned(
    *,
    block_id: str = BLOCK_ID,
    start: str = "2026-02-10T07:00:00+00:00",
    end: str = "2026-02-10T09:30:00+00:00",
    pin_verdict: dict[str, Any] | None = None,
    pin_operation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """What one edit answers with: the pin, the live verdict, and the solve to follow."""
    return {
        "pin": {
            "id": PIN_ID,
            "isoWeek": ISO_WEEK,
            "blockId": block_id,
            "interval": span(start, end),
            "supersededPlacement": span("2026-02-10T05:30:00+00:00", "2026-02-10T08:00:00+00:00"),
            "objectiveDelta": 0.4,
            "weightSetVersion": 1,
            "createdAt": "2026-02-09T09:00:00+00:00",
        },
        "verdict": (
            verdict(feasible=True, shortfalls=[], tradeoffs=0)
            if pin_verdict is None
            else pin_verdict
        ),
        "operation": operation() if pin_operation is None else pin_operation,
    }


def approved(
    *,
    input_version: int = 8,
    solved_against_version: int = 7,
    reason: str = "user_approved",
    adjustment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """What one approval wrote, and the projection it queued."""
    return {
        "revisionId": REVISION_ID,
        "isoWeek": ISO_WEEK,
        "reason": reason,
        "approvedAt": "2026-02-09T09:05:00+00:00",
        "inputVersion": input_version,
        "solvedAgainstVersion": solved_against_version,
        "adjustment": adjustment,
        "projection": operation(kind="projection", identifier=PROJECTION_ID),
    }


def metadata(base_url: str) -> dict[str, Any]:
    """The RFC 8414 document, as the api builds it from its pinned issuer."""
    return {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/oauth/authorize",
        "token_endpoint": f"{base_url}/oauth/token",
        "revocation_endpoint": f"{base_url}/oauth/revoke",
        "jwks_uri": f"{base_url}/.well-known/jwks.json",
        "scopes_supported": ["plan:read", "plan:write", "admin"],
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "revocation_endpoint_auth_methods_supported": ["none"],
    }


# The claim set the api mints, in the shape it mints it. Signed with a value that is not a
# signature, because nothing in the CLI verifies one: the api does that, against a key set, and a
# test that supplied a real ES256 signature would be testing PyJWT.
ACCESS_TOKEN_EXPIRES_AT = 1_770_000_900


def access_token(
    *,
    scopes: tuple[str, ...] = ("plan:read", "plan:write"),
    tenant_id: str = TENANT_ID,
    user_id: str = USER_ID,
    expires_at: int = ACCESS_TOKEN_EXPIRES_AT,
    client_id: str = "syncr-cli",
) -> str:
    """An access token shaped exactly as the api's, for the claims a status reads."""
    header = _segment({"alg": "ES256", "kid": "a-key", "typ": "JWT"})
    claims = _segment(
        {
            "iss": "http://localhost",
            "sub": user_id,
            "aud": "http://localhost/api/v1",
            "iat": expires_at - 900,
            "exp": expires_at,
            "tid": tenant_id,
            "scope": " ".join(scopes),
            "client_id": client_id,
        }
    )
    return f"{header}.{claims}.{_encode(b'not-a-signature')}"


def token_response(
    *,
    refresh: str = "syncrr_second",
    scopes: tuple[str, ...] = ("plan:read", "plan:write"),
    access: str | None = None,
) -> dict[str, Any]:
    """What the token endpoint answers, in RFC 6749's own member names."""
    return {
        "access_token": access_token(scopes=scopes) if access is None else access,
        "token_type": "Bearer",
        "expires_in": 900,
        "refresh_token": refresh,
        "scope": " ".join(scopes),
    }


def _segment(claims: dict[str, Any]) -> str:
    return _encode(json.dumps(claims, separators=(",", ":")).encode("utf-8"))


def claims_without(claim: str) -> str:
    """The claim set an access token carries, less one claim, as its own segment.

    For the readings that have to hold when a deployment's claim set is not this one: a status is a
    display reading of someone else's document, so a claim this build does not find is reported as
    absent rather than faulted over.
    """
    claims = {
        "iss": "http://localhost",
        "sub": USER_ID,
        "aud": "http://localhost/api/v1",
        "iat": ACCESS_TOKEN_EXPIRES_AT - 900,
        "exp": ACCESS_TOKEN_EXPIRES_AT,
        "tid": TENANT_ID,
        "scope": "plan:read plan:write",
        "client_id": "syncr-cli",
    }
    del claims[claim]
    return _segment(claims)


def _encode(raw: bytes) -> str:
    return urlsafe_b64encode(raw).decode("ascii").rstrip("=")
