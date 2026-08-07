"""The product's routes, as this client calls them, and the whole inventory of what it can reach.

One method per operation rather than one generic ``request``, so each is independently substitutable
in a test with a single return shape and no conditional inside a stub. The bearer credential is
attached by the session, which obtains it lazily: a command that never calls a method here never
refreshes a token.

**Every route is a named template and the set of them is closed.** Section 17's out-of-scope list --
notifications and SSE, the weekly session ritual, the pie review, template editing, calendar source
setup -- is a boundary only if nothing here can reach it, so the templates are constants a test
reads rather than strings spelled inside twelve methods. The CLI also requests neither the ``admin``
scope nor any route that needs it, so the boundary holds twice over.

``/api/v1`` is stated here because discovery does not carry it. The versioned prefix is the
resource server, which is exactly what an access token's audience names, so the constant and the
``aud`` claim are the same string and a mismatch shows up as a rejected token rather than as a
404.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, Protocol

from syncr_cli.idempotency import IDEMPOTENCY_KEY_HEADER

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date

    from syncr_cli.http import Transport
    from syncr_cli.wire.reading import JsonMapping

API_PREFIX: Final = "/api/v1"

# The route templates, under the prefix. Every one of them serves a command in the catalog; a test
# asserts the set is exactly this and that none of it names an out-of-scope resource.
AREAS: Final = "/areas"
TASKS: Final = "/tasks"
TASK_COMPLETE: Final = "/tasks/{task_id}/complete"
WEEK: Final = "/weeks/{iso_week}"
WEEK_SOLVE: Final = "/weeks/{iso_week}/solve"
WEEK_APPROVE: Final = "/weeks/{iso_week}/approve"
WEEK_PINS: Final = "/weeks/{iso_week}/pins"
BLOCK_OUTCOME: Final = "/blocks/{block_id}/outcome"
DAY: Final = "/days/{date}"
DAY_CONFIRM: Final = "/days/{date}/confirm"
OPERATION: Final = "/operations/{operation_id}"

ROUTES: Final = frozenset(
    {
        AREAS,
        TASKS,
        TASK_COMPLETE,
        WEEK,
        WEEK_SOLVE,
        WEEK_APPROVE,
        WEEK_PINS,
        BLOCK_OUTCOME,
        DAY,
        DAY_CONFIRM,
        OPERATION,
    }
)

# The query parameter that bypasses the debounce a solve would otherwise wait out.
IMMEDIATE: Final = "immediate"


class Credential(Protocol):
    """What a request presents. Satisfied by :class:`~syncr_cli.auth.session.Session`.

    A protocol rather than the class, so this module depends on the one thing it uses -- a header
    -- and not on how that header is obtained. It also means nothing here can reach into a session
    and refresh it out of turn.
    """

    def headers(self) -> dict[str, str]:
        """The ``Authorization`` header a request carries."""
        ...


class ApiClient:
    """The syncr API, as the commands in this package use it."""

    def __init__(self, *, transport: Transport, api_url: str, session: Credential) -> None:
        self._transport = transport
        self._api_url = api_url
        self._session = session

    def read_week(self, iso_week: str) -> Any:
        """The composed week view: the plan, or the reason there is none."""
        return self._get(WEEK.format(iso_week=iso_week))

    def list_areas(self) -> Any:
        """Every Area this tenant has declared, which is how a ledger names one."""
        return self._get(AREAS)

    def read_operation(self, operation_id: str) -> Any:
        """One tracked long-running job, as a wait polls it."""
        return self._get(OPERATION.format(operation_id=operation_id))

    def list_tasks(self, *, area_id: str | None = None, status: str | None = None) -> Any:
        """The backlog, with the header counts the server computed."""
        stated = {"areaId": area_id, "status": status}
        return self._get(
            TASKS, params={name: value for name, value in stated.items() if value is not None}
        )

    def read_day(self, on: date) -> Any:
        """One date's ledger: what has ended, what has not, and what was recorded."""
        return self._get(DAY.format(date=on.isoformat()))

    def capture_task(self, body: JsonMapping, *, key: str) -> Any:
        """Capture a task. A title and an Area; everything else has a documented default."""
        return self._post(TASKS, body, key=key)

    def complete_task(self, task_id: str, *, key: str) -> Any:
        """Complete a task. It leaves solver eligibility and keeps its recorded time."""
        return self._post(TASK_COMPLETE.format(task_id=task_id), {}, key=key)

    def confirm_day(self, on: date, *, key: str) -> Any:
        """Answer for every block of one date, converting presumption into record."""
        return self._post(DAY_CONFIRM.format(date=on.isoformat()), {}, key=key)

    def record_outcome(self, block_id: str, body: JsonMapping, *, key: str) -> Any:
        """State what happened to one block."""
        return self._put(BLOCK_OUTCOME.format(block_id=block_id), body, key=key)

    def create_pin(self, iso_week: str, body: JsonMapping, *, key: str) -> Any:
        """Move a block, which creates a pin and answers with the resulting verdict."""
        return self._post(WEEK_PINS.format(iso_week=iso_week), body, key=key)

    def approve_week(self, iso_week: str, *, key: str) -> Any:
        """Approve the pending proposal. The one route that demands a key."""
        return self._post(WEEK_APPROVE.format(iso_week=iso_week), {}, key=key)

    def request_solve(self, iso_week: str, *, immediate: bool = False) -> Any:
        """Ask for a plan for this week, and answer with the operation to follow.

        **The only mutation this client sends no derived key on.** A solve is already idempotent per
        week by the coordinator's single-flight invariant, and a key derived from the command would
        be the same key tomorrow: the api's guard would replay the completed operation rather than
        dispatching a solve of a week that has since moved on. A caller who wants a key states one.
        """
        return self._post(
            WEEK_SOLVE.format(iso_week=iso_week),
            {},
            params={IMMEDIATE: "true"} if immediate else None,
        )

    def _get(self, path: str, *, params: Mapping[str, str] | None = None) -> Any:
        return self._transport.get(self._url(path), params=params, headers=self._headers())

    def _post(
        self,
        path: str,
        body: JsonMapping,
        *,
        key: str | None = None,
        params: Mapping[str, str] | None = None,
    ) -> Any:
        return self._transport.post_json(
            self._url(path), body, params=params, headers=self._headers(key)
        )

    def _put(self, path: str, body: JsonMapping, *, key: str) -> Any:
        return self._transport.put_json(self._url(path), body, headers=self._headers(key))

    def _url(self, path: str) -> str:
        return f"{self._api_url}{API_PREFIX}{path}"

    def _headers(self, key: str | None = None) -> Mapping[str, str]:
        """The credential, and the idempotency key when this request carries one."""
        headers = dict(self._session.headers())
        if key is not None:
            headers[IDEMPOTENCY_KEY_HEADER] = key
        return headers
