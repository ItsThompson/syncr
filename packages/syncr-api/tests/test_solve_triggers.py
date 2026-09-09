"""The declared trigger table, and the version bump every mutating route owes, as two enumerations.

Both rules degrade silently. A route added later that forgets its bump leaves a running solve
believing it read current inputs, and a trigger the table names that reaches no solve leaves a
mechanism with nothing to drive it. Neither shows up as a failing test unless something enumerates
the whole set, so that is what this file does.

## The trigger table is data here, one row per declared trigger

Each row states two things: whether it bumps the week's input version, and whether it asks for a
solve. A row is either WIRED, meaning the code performs what the row says, or it is EXCLUDED with a
named owner. There is no third state: a row that is neither fails.

**What the enumeration found, and it is the reason it was asked for.** Twelve of the twenty rows
that ask for a solve reach none. `kind = "solve"` is created only through
``SolveCoordinator.request_solve``, whose call sites are in `pins`, `learned`, `plans`, `conflicts`,
`concessions`, `calendars` and the horizon maintainer, so the debounce, the coalescing and the
supersession machinery are driven by those call sites, two of which bypass the debounce window by
design: the re-solve control asks for an immediate pass, and so does a tradeoff request.

That is not a defect in any one of the twelve: each bumps correctly, and a bump is what makes a
running solve's conditional write fail. What is missing is the request that follows it. The
exclusions below name the owner that owes each one.

## The bump walk is stated over SOLVE-INPUT-mutating routes

"Every mutating endpoint" cannot be taken literally: signing in mutates a session table, the OAuth
token endpoint mutates a grant, and connecting a Google account mutates a credential. None of those
touches a week's solve inputs, and requiring a bump of them would be requiring a bump of a week none
of them names. So the walk is stated over the routes that change what a solve READS, the allowlist
holds exactly the one row the table puts in it, and what is outside the rule is listed with the
reason each is outside.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING, Final, NamedTuple

import pytest

from syncr_api.accounts.config import AUTH_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.settings import API_PREFIX
from syncr_api.oauth.config import OAUTH_PREFIX
from syncr_api.solving.config import SOLVE
from tests.boundaries import METHODS_WITHOUT_A_BODY, api_routes, route_identity

if TYPE_CHECKING:
    from syncr_api.core.settings import ServiceSettings

SOURCE_ROOT: Final = Path(__file__).resolve().parents[1] / "src" / "syncr_api"

# The one call that creates a `solve` operation. Every trigger that asks for a solve reaches this,
# and a trigger that does not reach it does not solve, whatever it bumps.
REQUESTS_A_SOLVE: Final = "coordinator.request_solve"

# What a module has to contain to be bumping a week's input version. Three spellings because three
# shapes of mutation exist: one week, an enumerated range of weeks, and every week from the current
# one onwards. Matched on the CALL rather than on a name, so an annotation naming the repository is
# not read as performing the write.
BUMPS_A_VERSION: Final = ("versions.bump(", "from_the_week_holding(", "bump(WeekRange(")


class Trigger(NamedTuple):
    """One row of the trigger table, and what the code does about it.

    ``module`` is where this row's own write lives. ``solves_in`` names where its solve request
    lives for the one row whose two halves are in different packages, and is ``None`` everywhere
    else: a trigger whose bump sits beside the rows it invalidates and whose request sits at the
    seam that performs the pass cannot be answered for by one path.

    ``owner`` is ``None`` for a row the code performs. For a row it does not, it names the work
    that owes the wiring, so an unwired trigger is a diff a reviewer reads rather than a silence.
    """

    row: str
    bumps: bool
    solves: bool
    module: str | None
    solves_in: str | None = None
    owner: str | None = None


# ---------------------------------------------------------------------------
# THE TRIGGER TABLE, one entry per row, in the table's own order.
#
# `module` is where the trigger's own write lives, and it is what the walk below reads. A row with
# an
# `owner` is one the code does not perform yet: the owner named owes it, and the row stays here so
# the gap is enumerated rather than absent.
# ---------------------------------------------------------------------------
TRIGGER_TABLE: Final[tuple[Trigger, ...]] = (
    Trigger("pin, unpin, drag, keyboard move", bumps=True, solves=True, module="pins/service.py"),
    Trigger(
        "task added, edited, completed, dropped",
        bumps=True,
        solves=True,
        module="tasks/service.py",
        solves_in="solving/injection.py",
    ),
    Trigger(
        "habit added or edited",
        bumps=True,
        solves=True,
        module="habits/service.py",
        owner="1403",
    ),
    Trigger(
        "routine added or edited",
        bumps=True,
        solves=True,
        module="routines/service.py",
        owner="1403",
    ),
    Trigger(
        "preference added, edited, removed",
        bumps=True,
        solves=True,
        module="preferences/service.py",
        owner="1403",
    ),
    Trigger(
        "template or template entry edited",
        bumps=True,
        solves=True,
        module="templates/invalidation.py",
        owner="1403",
    ),
    Trigger(
        "week pattern edited",
        bumps=True,
        solves=True,
        module="templates/invalidation.py",
        owner="1403",
    ),
    Trigger(
        "area budget, floor, or percentage edited",
        bumps=True,
        solves=True,
        module="areas/service.py",
        owner="1403",
    ),
    Trigger(
        "off-plan period declared, edited, removed",
        bumps=True,
        solves=True,
        module="offplan/service.py",
        owner="1403",
    ),
    Trigger(
        "home zone or travel override changed",
        bumps=True,
        solves=True,
        module="user_settings/service.py",
        owner="1403",
    ),
    Trigger(
        "day confirmed or a past confirmation corrected",
        bumps=True,
        solves=True,
        module="outcomes/service.py",
        owner="1403",
    ),
    Trigger(
        "anchor delta from a calendar sync",
        bumps=True,
        solves=True,
        module="anchors/reconcile.py",
        solves_in="calendars/solve_requests.py",
    ),
    Trigger(
        "anchor type added, edited, reordered",
        bumps=True,
        solves=True,
        module="anchors/service.py",
        owner="1403",
    ),
    Trigger(
        "conflict resolved as moved or retyped",
        bumps=True,
        solves=True,
        module="conflicts/service.py",
    ),
    Trigger(
        "conflict resolved as kept-both",
        bumps=False,
        solves=False,
        module="conflicts/service.py",
    ),
    Trigger(
        "tradeoff requested",
        bumps=False,
        solves=True,
        module="concessions/service.py",
    ),
    Trigger(
        "tradeoff approved",
        bumps=True,
        solves=False,
        module="approvals/service.py",
    ),
    Trigger(
        "proposal approved",
        bumps=True,
        solves=False,
        module="approvals/service.py",
    ),
    Trigger(
        "week adjustment revoked",
        bumps=True,
        solves=True,
        module="concessions/service.py",
    ),
    Trigger("re-solve control", bumps=False, solves=True, module="plans/service.py"),
    Trigger(
        "weight set activated or reverted",
        bumps=True,
        solves=True,
        module="learned/activation.py",
    ),
    Trigger(
        "a week enters the projection horizon",
        bumps=True,
        solves=True,
        module="horizon/maintainer.py",
    ),
    Trigger(
        "projection horizon length changed",
        bumps=True,
        solves=True,
        module="calendars/service.py",
        owner="1403",
    ),
    Trigger("zoom, selection, scroll, panel open", bumps=False, solves=False, module=None),
    Trigger("reading any screen", bumps=False, solves=False, module=None),
)

# The routes outside the bump rule, each for a stated reason. None of them names a week and none of
# them changes what a solve reads, so requiring a bump of one would be requiring a bump of nothing.
#
#   /auth/*         signs in and out. It writes a session, which is not a solve input
#   /oauth/*        issues, revokes and consents to a credential. Same reason
#   the Google connect flow writes a credential and nothing about a week. Designating a WRITE TARGET
#                   is a different route, it changes which weeks need a plan, and it bumps: that one
#                   is `calendars` and it is in the table above
#   /events         is a read whose body never ends. It holds no session, so it cannot write
#
# The first two are DOCUMENTATION rather than exclusions: the walk filters on the api prefix first,
# and neither is under it, so deleting either entry would change nothing. What keeps that safe is
# the credential-routes assertion below, which closes the set outside the prefix. The other two do
# exclude, and adding an entry beside them is adding a hole in the rule: that is the point of
# keeping the list in the file named for it.
OUTSIDE_THE_RULE: Final = (
    AUTH_PREFIX,
    OAUTH_PREFIX,
    f"{API_PREFIX}/calendar-sources/google/connect",
    f"{API_PREFIX}/events",
)

# The one route allowed to mutate without bumping. It records a decision, changes no solve
# input and changes no live plan, so there is nothing for a running solve to be invalidated by.
KEPT_BOTH_ROUTE: Final = f"{API_PREFIX}/conflicts"

# The second prefix outside the per-package reading, and it is outside for a different reason: its
# accept DOES bump, through the day-shape service it delegates the write to, so the bump is in
# `templates` where the day-shape trigger row already names it. Its decline bumps nothing and owes
# nothing: a declined promotion records an answer about what to ASK, and no solve reads it.
#
# Stated as a prefix with two checked claims rather than as a hole:
# `test_the_promotion_prefix_holds_the_two_routes_the_reason_names` bounds what it covers, and
# `test_the_promotion_accept_bumps_through_the_day_shape_service` follows the delegation to the
# bump.
PROMOTIONS_ROUTE: Final = f"{API_PREFIX}/promotions"

# Every prefix the per-package bump reading does not answer for, each with a test naming why.
OUTSIDE_THE_PACKAGE_READING: Final = (KEPT_BOTH_ROUTE, PROMOTIONS_ROUTE)


# The two modules that compose the anchor reconciler: one per entry point into a sync. A pass
# invalidates the weeks it moved occupancy in, so a composition that omits the counter produces a
# reconciler that writes anchors and tells no solve about them.
ANCHOR_RECONCILER_COMPOSITIONS: Final = ("calendars/injection.py", "calendars/runner.py")


# Where a composition may read the tenant's home zone from. Both entry points into a sync already
# hold the row: the request side has the zone profile it built for the adapters, and the worker's
# poll has the settings it read for the same profile. A third name arriving here is a third place
# the value could come from, and it has to be justified rather than inherited.
TENANT_ZONE_SOURCES: Final = frozenset({"profile", "settings"})


# The one row whose bump and whose solve request are in different packages, and the module each
# half is in. The bump belongs beside the anchor rows it invalidates; the request belongs at the
# seam that performs a pass, because both entry points into a sync arrive there. Bounded as a set
# rather than left open, so a later row cannot inherit an exemption written about this one.
ANCHOR_DELTA_ROW: Final = "anchor delta from a calendar sync"
SOLVES_ELSEWHERE: Final = {
    ANCHOR_DELTA_ROW: "calendars/solve_requests.py",
    "task added, edited, completed, dropped": "solving/injection.py",
}


def solve_module(trigger: Trigger) -> str | None:
    """Where this row's solve request lives: its own module unless the row names another."""
    return trigger.solves_in or trigger.module


def reconciler_call(module: str) -> ast.Call:
    """The one ``AnchorReconciler(...)`` construction in ``module``.

    Parsed rather than matched as text, so the keywords are read from the call itself and a
    mention of one in a comment or a docstring cannot stand in for passing it.
    """
    tree = ast.parse(module_source(module))
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "AnchorReconciler"
    ]
    assert len(found) == 1, f"{module} composes {len(found)} reconcilers, not one"
    return found[0]


def module_source(module: str | None) -> str:
    """The source of a module a row names.

    Takes the optional type the row carries, and refuses ``None`` rather than being handed a
    narrowed value by each caller: a row with no module is one whose endpoint does not exist, and
    the parametrizations that reach here have already filtered those out. A refusal names the
    mistake.
    """
    if module is None:
        message = "a row with no module has no source to read: filter it out of the parametrization"
        raise AssertionError(message)
    return (SOURCE_ROOT / module).read_text(encoding="utf-8")


def api_route_pairs(settings: ServiceSettings) -> set[tuple[str, str]]:
    """Every ``(method, path)`` pair the application answers."""
    return {pair for route in api_routes(create_app(settings)) for pair in route_identity(route)}


class MutatingRoute(NamedTuple):
    """One route with a body, and the package whose module declared it."""

    method: str
    path: str
    package: str


def mutating_routes(settings: ServiceSettings) -> list[MutatingRoute]:
    """Every route under the api prefix that has a body, with its owning package.

    The package comes from the endpoint's own module rather than from the route's path. A path is a
    product decision (``/anchor-types``, ``/off-plan``, ``/blocks/{id}/outcome``) and matching one
    against a package name is a lookup table that goes stale the first time a route is renamed. The
    endpoint knows which module declared it, so the pairing is derived from the thing that emits it.
    """
    found: list[MutatingRoute] = []
    for route in api_routes(create_app(settings)):
        package = owning_package(route.endpoint)
        found.extend(
            MutatingRoute(method, path, package)
            for method, path in route_identity(route)
            if method not in METHODS_WITHOUT_A_BODY
            and path.startswith(API_PREFIX)
            and not any(path.startswith(prefix) for prefix in OUTSIDE_THE_RULE)
        )
    return sorted(found)


def owning_package(endpoint: object) -> str:
    """The ``syncr_api`` package the handler was declared in, as one segment."""
    module = getattr(endpoint, "__module__", "")
    parts = module.split(".")
    return parts[1] if len(parts) > 1 else module


def packages_that_bump() -> set[str]:
    """Every package holding a module that bumps a week's input version.

    Read off the source tree rather than from the trigger table, so the two are crossed against each
    other: a package that bumps and is in no row, or a row naming a package that does not, fails.
    """
    return {
        path.relative_to(SOURCE_ROOT).parts[0]
        for path in SOURCE_ROOT.rglob("*.py")
        if any(spelling in path.read_text(encoding="utf-8") for spelling in BUMPS_A_VERSION)
    }


class TestTheTriggerTable:
    def test_every_row_of_the_table_is_enumerated_once(self) -> None:
        """Twenty-five rows, the whole declared table. Asserted so a row cannot be
        dropped."""
        rows = [one.row for one in TRIGGER_TABLE]

        assert len(rows) == len(set(rows))
        assert len(rows) == 25

    @pytest.mark.parametrize(
        "trigger",
        [one for one in TRIGGER_TABLE if one.bumps and one.module is not None],
        ids=lambda one: one.row,
    )
    def test_a_row_that_bumps_has_a_module_that_bumps(self, trigger: Trigger) -> None:
        """Every trigger the table says invalidates a week reaches the version counter.

        Read from the module's source rather than by driving the route, because what has to hold is
        that the write is THERE: a route test proves one path and this proves the set.

        A row with no module has no endpoint to read, and it is left out of the parametrization
        rather than skipped: a skip reports forever and says nothing, while its absence is covered
        by ``test_a_row_with_no_module_is_one_whose_endpoint_does_not_exist`` below, which names the
        three and the owner of each.
        """
        body = module_source(trigger.module)

        assert any(spelling in body for spelling in BUMPS_A_VERSION), trigger.row

    def test_every_row_that_bumps_names_a_module_that_exists(self) -> None:
        """Every row the table says invalidates a week now has somewhere to read that from.

        The set of unreadable rows is EMPTY, and a row added later without an endpoint fails here
        rather than quietly leaving the walk above with nothing to read.
        """
        unreadable = {
            one.row: one.owner for one in TRIGGER_TABLE if one.module is None and one.bumps
        }

        assert unreadable == {}

    @pytest.mark.parametrize(
        "trigger",
        [one for one in TRIGGER_TABLE if not one.bumps and one.module is not None],
        ids=lambda one: one.row,
    )
    def test_a_row_that_does_not_bump_is_one_of_the_two_the_table_exempts(
        self, trigger: Trigger
    ) -> None:
        # `kept-both` records a decision and changes nothing; a tradeoff request and the re-solve
        # control each ask for a pass over inputs nobody changed. Anything else not bumping would be
        # a mutation a running solve could not see.
        assert trigger.row in {
            "conflict resolved as kept-both",
            "tradeoff requested",
            "re-solve control",
        }

    @pytest.mark.parametrize(
        "trigger",
        [one for one in TRIGGER_TABLE if one.solves and one.owner is None],
        ids=lambda one: one.row,
    )
    def test_a_wired_row_that_solves_reaches_the_coordinator(self, trigger: Trigger) -> None:
        asking = solve_module(trigger)
        assert asking is not None
        body = module_source(asking)

        assert REQUESTS_A_SOLVE in body, trigger.row

    @pytest.mark.parametrize(
        "trigger",
        [one for one in TRIGGER_TABLE if not one.solves and one.module is not None],
        ids=lambda one: one.row,
    )
    def test_a_row_that_never_solves_states_why_it_asks_for_nothing(self, trigger: Trigger) -> None:
        """Three rows, and two reasons.

        ``kept-both`` records a decision and changes nothing at all. The two approvals change the
        LIVE PLAN and still ask for nothing: the bump is what a RUNNING solve has to see, and the
        document the user approved IS the plan of record, so a solve requested here would propose
        changing what they just accepted.

        The source half of this rule is the test below, which cannot be stated over every row of
        this set.
        """
        assert trigger.row in {
            "conflict resolved as kept-both",
            "tradeoff approved",
            "proposal approved",
        }

    @pytest.mark.parametrize(
        "trigger",
        [
            one
            for one in TRIGGER_TABLE
            if not one.solves
            and one.module is not None
            and not any(other.solves and other.module == one.module for other in TRIGGER_TABLE)
        ],
        ids=lambda one: one.row,
    )
    def test_a_module_whose_every_row_asks_for_nothing_requests_no_solve(
        self, trigger: Trigger
    ) -> None:
        """The source half, and what makes the name half above a guard rather than a restatement.

        Its sibling reads the module's source for the bump. Without the same reading here, a module
        behind one of these rows could gain a solve request and every test in this file would still
        pass, which is what the reverse guard one screen down cannot cover for a row with no owner.

        Stated over the rows whose module serves NO row that solves, which is derived from the table
        rather than listed: ``conflicts/service.py`` answers both resolutions, so the source of the
        module says nothing about the ``kept-both`` branch, and
        ``test_the_kept_both_branch_is_the_one_that_bumps_nothing`` is that branch's own assertion.
        """
        body = module_source(trigger.module)

        assert REQUESTS_A_SOLVE not in body, trigger.row

    def test_reading_a_screen_and_moving_the_viewport_reach_neither(self) -> None:
        """The two rows that must reach nothing at all, and they have no module by construction.

        A read that queued work would make navigation a mutation. The runtime half of this is
        ``test_horizon_maintainer.py``'s read-never-writes walk, which drives every parameterless
        GET and counts rows; this half is that neither row has a write to point at.
        """
        never = [one for one in TRIGGER_TABLE if one.row.startswith(("zoom", "reading"))]

        assert len(never) == 2
        for one in never:
            assert not one.bumps
            assert not one.solves
            assert one.module is None


class TestTheUnwiredRowsAreEnumeratedRatherThanAbsent:
    """Twelve rows ask for a solve and reach none. Named here so the gap is countable.

    Building this enumeration is what made them visible, and BOTH directions are guarded, which is
    what makes the table's own claim true: a row that loses its bump fails the walk above, and a row
    that gains its solve request without losing its owner here fails
    ``test_a_row_that_still_names_an_owner_has_not_been_wired``. Without that second half the
    enumeration could not see the one change it exists to track, so it would have gone stale in
    exactly the direction this area travels.
    """

    def test_the_unwired_count_is_what_the_walk_found(self) -> None:
        """Eleven rows ask for a solve and reach none, all eleven a person's own mutation."""
        unwired = [one for one in TRIGGER_TABLE if one.solves and one.owner is not None]
        by_a_person = [one for one in unwired if one.owner != "1400"]

        assert len(unwired) == 11
        assert len(by_a_person) == 11

    @pytest.mark.parametrize(
        "trigger",
        [one for one in TRIGGER_TABLE if one.owner is not None and one.module is not None],
        ids=lambda one: one.row,
    )
    def test_a_row_that_still_names_an_owner_has_not_been_wired(self, trigger: Trigger) -> None:
        """The reverse guard, and the direction this area actually travels.

        A row loses its owner when it gains its request, and this is what forces the pair to move
        together: wiring one without editing the table fails here, so the enumeration cannot report
        a gap that has been closed. It is the same pattern ``OUTSIDE_THE_RULE`` already has one
        screen down, applied to the half that was missing it.
        """
        asking = solve_module(trigger)
        assert asking is not None
        body = module_source(asking)

        assert REQUESTS_A_SOLVE not in body, (
            f"{asking} now requests a solve, so the {trigger.row!r} row is wired: drop its "
            f"owner ({trigger.owner}) from TRIGGER_TABLE, and correct the counts beside it."
        )

    def test_every_unwired_row_names_a_ticket(self) -> None:
        for one in TRIGGER_TABLE:
            if one.owner is None:
                continue
            assert one.owner == "1403", one.row

    def test_only_nine_rows_reach_the_coordinator_today(self) -> None:
        # The nine live triggers, one of which bypasses the debounce by design. The calendar sync
        # and the week entering the horizon are the two triggers here that no person performs: a
        # poll asks for the weeks its own read moved, and time passing asks for the weeks it brought
        # in.
        wired = [one.row for one in TRIGGER_TABLE if one.solves and one.owner is None]

        assert sorted(wired) == [
            "a week enters the projection horizon",
            "anchor delta from a calendar sync",
            "conflict resolved as moved or retyped",
            "pin, unpin, drag, keyboard move",
            "re-solve control",
            "task added, edited, completed, dropped",
            "tradeoff requested",
            "week adjustment revoked",
            "weight set activated or reverted",
        ]

    def test_the_only_rows_whose_solves_live_outside_their_own_modules_are_declared(
        self,
    ) -> None:
        """The hole ``solves_in`` opens, bounded to the rows it was written for.

        Without this, a row could point ``solves_in`` at any module that happens to request a solve
        and the wired walk would pass while nothing about that row was wired. Which rows may name a
        second module is settled here; which module each names is settled below, so a row that loses
        the field and a row that points it somewhere else are two different failures.
        """
        naming = {one.row for one in TRIGGER_TABLE if one.solves_in is not None}

        assert naming == set(SOLVES_ELSEWHERE)

    def test_the_anchor_delta_asks_for_its_solve_through_the_pass_that_reconciled_it(self) -> None:
        """The delegation ``solves_in`` rests on, followed from the row to the pass to the request.

        This row's two halves are in two packages, so the reading that answers for it has to cross
        the seam between them: the pass that reconciles the anchors hands the weeks the
        reconciliation invalidated to the collaborator that asks, and that collaborator is what
        reaches the coordinator. Reading one end alone would let either half go missing with the
        other still green, and reading neither would let the row name a module that asks about some
        other trigger entirely.
        """
        row = next(one for one in TRIGGER_TABLE if one.row == ANCHOR_DELTA_ROW)

        assert row.solves_in == SOLVES_ELSEWHERE[ANCHOR_DELTA_ROW]
        assert "self._solves.request(delta.occupied_weeks)" in module_source("calendars/sync.py")
        assert REQUESTS_A_SOLVE in module_source(row.solves_in)

    def test_the_task_row_asks_the_composed_solve_request_adapter(self) -> None:
        row = next(one for one in TRIGGER_TABLE if one.row.startswith("task added"))

        assert row.solves_in == SOLVES_ELSEWHERE[row.row]
        assert "self._solve_requests.request(" in module_source(row.module)
        assert REQUESTS_A_SOLVE in module_source(row.solves_in)

    def test_the_solve_kind_has_exactly_one_creation_path(self) -> None:
        """Which is what makes the count above the whole truth rather than a sample.

        If a second path created a `solve` operation, a trigger could reach one without reaching the
        coordinator and the enumeration would be measuring the wrong thing.

        Both spellings are searched. ``OperationKind`` is a ``Literal``, so ``kind="solve"`` written
        out type-checks exactly as the constant does, and a walk that matched only the constant
        would be evaded by the more likely of the two mistakes.
        """
        spellings = (f"kind={SOLVE.upper()}", f'kind="{SOLVE}"')
        creating = sorted(
            str(path.relative_to(SOURCE_ROOT))
            for path in SOURCE_ROOT.rglob("*.py")
            if any(one in path.read_text(encoding="utf-8") for one in spellings)
        )

        assert creating == ["solving/coordinator.py"]


class TestEveryMutatingRouteBumpsOrIsTheAllowlistMember:
    """The runtime half: every route with a body reaches a bump, or it is the one exempt route.

    Stated over the routes that change what a solve READS. The routes outside that are listed in
    ``OUTSIDE_THE_RULE`` with the reason each is outside, and the list has its own reverse guard, so
    an exclusion cannot outlive the route it was written for.

    **The granularity is the PACKAGE, not the route, and that is a real limit.** What this walk
    asserts is that a route's package bumps somewhere, so one route of a package forgetting its own
    bump passes here. The per-route half is carried by each feature's own suite:
    ``test_tasks_service``, ``test_habits_service``, ``test_areas_service`` and their siblings each
    assert their own writes bump. What this adds is that no route belongs to a package with no bump
    at all, which is the failure a feature suite cannot see, because it does not know the route
    exists. Deriving the pairing per route would need a second hop below the service method, of
    which ``tests/boundaries.py`` resolves one; it is worth doing the day a package holds a route
    that must not bump.

    **The walk is bounded by the api prefix**, and the routes outside it are asserted rather than
    assumed, so a solve-input-mutating route added outside ``/api/v1``, a provider webhook being the
    plausible one, has to be classified rather than silently exempt.
    """

    def test_the_walk_finds_routes_at_all(self, settings: ServiceSettings) -> None:
        assert mutating_routes(settings), "no mutating route was found, so this asserted nothing"

    def test_the_body_bearing_routes_outside_the_api_prefix_are_exactly_the_credential_ones(
        self, settings: ServiceSettings
    ) -> None:
        """So a mutation added outside the prefix cannot be exempt by the filter alone.

        The filter is what bounds the walk, not the exclusion list, and the two prefixes the list
        names for `/auth` and `/oauth` therefore document rather than exclude. What makes that safe
        is this assertion: the set outside the prefix is closed, and a new member fails here.
        """
        outside = sorted(
            (method, path)
            for method, path in api_route_pairs(settings)
            if method not in METHODS_WITHOUT_A_BODY and not path.startswith(API_PREFIX)
        )

        assert [path for _method, path in outside] == [
            f"{AUTH_PREFIX}/login",
            f"{AUTH_PREFIX}/logout",
            f"{OAUTH_PREFIX}/authorize/decision",
            f"{OAUTH_PREFIX}/revoke",
            f"{OAUTH_PREFIX}/token",
        ]

    def test_every_mutating_route_belongs_to_a_package_that_bumps(
        self, settings: ServiceSettings
    ) -> None:
        bumping = packages_that_bump()

        unaccounted = [
            (one.method, one.path, one.package)
            for one in mutating_routes(settings)
            if one.package not in bumping and not one.path.startswith(OUTSIDE_THE_PACKAGE_READING)
        ]

        assert unaccounted == [], (
            f"{unaccounted} mutate and reach no version bump. Every mutation that touches a week's "
            "solve inputs bumps that week's version in the same transaction, or a running solve "
            "believes it read current inputs."
        )

    def test_a_route_whose_package_does_not_bump_would_be_caught(self) -> None:
        """The control. Without it the walk passes forever the day the source pattern stops
        matching.

        A package invented here stands for one added later that forgot its bump: it is not in the
        bumping set and it is neither prefix outside the reading, so the rule has to report it.
        """
        invented = MutatingRoute("POST", f"{API_PREFIX}/widgets", "widgets")

        assert invented.package not in packages_that_bump()
        assert not invented.path.startswith(OUTSIDE_THE_PACKAGE_READING)

    def test_every_package_that_bumps_is_named_by_a_row_of_the_table(self) -> None:
        """The other direction, so the table and the tree are crossed rather than read separately.

        A package that bumps and appears in no row is a mutation the table does not describe, which
        is either a missing row or a bump nothing asked for. Two packages are exceptions and neither
        is a trigger of its own.

        ``solving`` bumps because the solve dispatch's own adoption changed the live plan.

        ``reviews`` bumps because applying the pie review's proposed percentages IS the "area
        budget, floor, or percentage edited" row, reached from a second surface. That row names
        ``areas/service.py``, which is the same mutation's other surface, and ``module`` holds one
        path: naming the second here rather than widening the field is the smaller change, and it is
        the limit the package granularity already has.
        """
        named = {one.module.split("/")[0] for one in TRIGGER_TABLE if one.module is not None}

        assert packages_that_bump() - named - {"solving", "reviews"} == set()

    def test_the_kept_both_allowlist_holds_exactly_one_route(
        self, settings: ServiceSettings
    ) -> None:
        # One row is in it: `kept-both`, which records a decision and changes neither a
        # solve input nor the live plan. The route it lives on answers both resolutions, so what is
        # allowlisted is the route and the branch inside it is what its own suite drives.
        exempt = [
            one.path for one in mutating_routes(settings) if one.path.startswith(KEPT_BOTH_ROUTE)
        ]

        assert exempt == [f"{KEPT_BOTH_ROUTE}/{{conflict_id}}/resolve"]

    def test_the_kept_both_branch_is_the_one_that_bumps_nothing(self) -> None:
        """Asserted on the source because the branch, not the route, is what the table exempts."""
        body = module_source("conflicts/service.py")
        bumping = body.index("versions.bump(")
        branch = body.index(
            "if chosen.resolution == KEPT_BOTH_RESOLUTION:\n            return None"
        )

        assert branch < bumping

    def test_the_promotion_prefix_holds_the_two_routes_the_reason_names(
        self, settings: ServiceSettings
    ) -> None:
        """The prefix is outside the per-package reading for two stated reasons, one per route.

        Bounding it here is what stops a third promotion route inheriting an exemption written about
        these two: a route added under this prefix arrives with no reason and fails.
        """
        under = sorted(
            one.path for one in mutating_routes(settings) if one.path.startswith(PROMOTIONS_ROUTE)
        )

        assert under == [
            f"{PROMOTIONS_ROUTE}/{{promotion_id}}/accept",
            f"{PROMOTIONS_ROUTE}/{{promotion_id}}/decline",
        ]

    def test_the_promotion_accept_bumps_through_the_day_shape_service(self) -> None:
        """The delegation the accept's exemption rests on, followed to the bump.

        A promotion moves an entry of a day shape, which is the "day shape or one of its
        entries edited" row reached from a second route. The write is the day-shape service's, so
        the bump is in ``templates`` and the per-package reading cannot see it from ``promotions``.
        What makes that safe is this: the accept really does call that service, that method really
        does invalidate, and the module it invalidates through really does bump.
        """
        accept = module_source("promotions/service.py")
        day_shapes = module_source("templates/service.py")
        invalidation = module_source("templates/invalidation.py")

        assert "self._templates.change_entry(" in accept
        assert "async def change_entry(" in day_shapes
        assert "await self._weeks.invalidate_if_mapped(shape.day_type_id)" in day_shapes
        assert any(spelling in invalidation for spelling in BUMPS_A_VERSION)

    def test_the_promotion_decline_writes_nothing_a_solve_reads(self) -> None:
        """The other half of the reason: a decline changes what is ASKED, not what is solved.

        Its only write is its own table, and no module outside this package reads it except the
        weekly session's raise, which is a read. So there is nothing for a running solve to be
        invalidated by, which is the same ground ``kept-both`` stands on.
        """
        service = module_source("promotions/service.py")

        assert "self._declines.decline(" in service
        assert not any(spelling in service for spelling in BUMPS_A_VERSION)

    @pytest.mark.parametrize("module", list(ANCHOR_RECONCILER_COMPOSITIONS), ids=lambda one: one)
    def test_every_composition_of_the_anchor_reconciler_hands_it_the_counter(
        self, module: str
    ) -> None:
        """The delegation the anchor-delta row rests on, followed to the collaborator.

        That row's write lives below a service rather than in one, so the per-package reading cannot
        see it: a sync is reached from a route and from the worker's poll, and the reconciler is
        composed once per entry point. A composition that omitted the counter would leave that entry
        point writing anchors and invalidating nothing, with every other test in this file green.

        Parametrized rather than looped, so a failure names WHICH entry point lost its counter: one
        of the two is a route and the other is a background poll, and they are fixed by different
        edits.
        """
        passed = {keyword.arg for keyword in reconciler_call(module).keywords}

        assert passed == {"versions", "home_zone"}, module

    @pytest.mark.parametrize("module", list(ANCHOR_RECONCILER_COMPOSITIONS), ids=lambda one: one)
    def test_the_zone_a_composition_passes_is_read_off_the_tenants_own_row(
        self, module: str
    ) -> None:
        """Which week an instant falls in is answered in the TENANT's home zone.

        One zone for every tenant would be wrong by a week at the seam for anyone east or west of
        it, and nothing downstream could detect it: the weeks invalidated would be plausible,
        adjacent, and stale.

        The shape is asserted, not merely the absence of a string. A module-level constant is as
        fixed as a literal and is an ``ast.Name`` rather than an ``ast.Constant``, so refusing
        literals alone would leave the defect one rename away. What has to hold is that the value is
        read as ``home_zone`` off something this module obtained from the tenant, which is what
        ``TENANT_ZONE_SOURCES`` names.
        """
        zone = next(
            keyword.value
            for keyword in reconciler_call(module).keywords
            if keyword.arg == "home_zone"
        )

        assert isinstance(zone, ast.Attribute), f"{module} passes {ast.dump(zone)}"
        assert zone.attr == "home_zone", module
        assert isinstance(zone.value, ast.Name), f"{module} passes {ast.dump(zone)}"
        assert zone.value.id in TENANT_ZONE_SOURCES, f"{module} reads it off {zone.value.id}"

    @pytest.mark.parametrize("prefix", list(OUTSIDE_THE_RULE), ids=lambda one: one)
    def test_every_exclusion_still_names_routes_that_exist(
        self, prefix: str, settings: ServiceSettings
    ) -> None:
        """So an exclusion cannot outlive what it was written for and quietly widen the hole."""
        every = {path for _method, path in api_route_pairs(settings)}

        assert any(path.startswith(prefix) for path in every), prefix
