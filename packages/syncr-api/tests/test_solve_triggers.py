"""Section 10's trigger table, and the version bump every mutating route owes, as two enumerations.

Both rules degrade silently. A route added later that forgets its bump leaves a running solve
believing it read current inputs, and a trigger the table names that reaches no solve leaves a
mechanism with nothing to drive it. Neither shows up as a failing test unless something enumerates
the whole set, so that is what this file does.

## The trigger table is data here, one row per row of section 10

Each row states two things: whether it bumps the week's input version, and whether it asks for a
solve. A row is either WIRED, meaning the code performs what the row says, or it is EXCLUDED with a
named owner ticket. There is no third state: a row that is neither fails.

**What the enumeration found, and it is the reason the criterion asked for it.** Fifteen of the
nineteen mutation rows bump the version and request NO solve. `kind = "solve"` is created only
through ``SolveCoordinator.request_solve``, which has four call sites, and the horizon maintainer
enqueues ``materialize`` rather than ``solve``. So the debounce, the coalescing and the supersession
machinery have four live triggers, one of which bypasses the debounce by design, and the
weekly-session burst of pins the 1500 ms window was measured against is not reachable at all,
because no pin endpoint exists yet.

That is not a defect in any one of the fifteen: each bumps correctly, and a bump is what makes a
running solve's conditional write fail. What is missing is the request that follows it. The
exclusions below name the ticket that owes each one.

## The bump walk is stated over SOLVE-INPUT-mutating routes

"Every mutating endpoint" cannot be taken literally: signing in mutates a session table, the OAuth
token endpoint mutates a grant, and connecting a Google account mutates a credential. None of those
touches a week's solve inputs, and requiring a bump of them would be requiring a bump of a week none
of them names. So the walk is stated over the routes that change what a solve READS, the allowlist
holds exactly the one row section 10 puts in it, and what is outside the rule is listed with the
reason each is outside.
"""

from __future__ import annotations

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
    """One row of section 10's trigger table, and what the code does about it.

    ``owner`` is ``None`` for a row the code performs. For a row it does not, it names the ticket
    that owes the wiring, so an unwired trigger is a diff a reviewer reads rather than a silence.
    """

    row: str
    bumps: bool
    solves: bool
    module: str | None
    owner: str | None = None


# ---------------------------------------------------------------------------
# SECTION 10'S TRIGGER TABLE, one entry per row, in the table's own order.
#
# `module` is where the trigger's own write lives, and it is what the walk below reads. A row with
# an
# `owner` is one the code does not perform yet: the ticket named owes it, and the row stays here so
# the gap is enumerated rather than absent.
# ---------------------------------------------------------------------------
TRIGGER_TABLE: Final[tuple[Trigger, ...]] = (
    Trigger("pin, unpin, drag, keyboard move", bumps=True, solves=True, module=None, owner="41"),
    Trigger(
        "task added, edited, completed, dropped",
        bumps=True,
        solves=True,
        module="tasks/service.py",
        owner="1403",
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
        module="calendars/service.py",
        owner="1403",
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
    Trigger("tradeoff approved", bumps=True, solves=False, module=None, owner="42"),
    Trigger("proposal approved", bumps=True, solves=False, module=None, owner="42"),
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
        module="reviews/service.py",
        owner="1403",
    ),
    Trigger(
        "a week enters the projection horizon",
        bumps=True,
        solves=True,
        module="plans/production.py",
        owner="1400",
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

# The one route section 10 allows to mutate without bumping. It records a decision, changes no solve
# input and changes no live plan, so there is nothing for a running solve to be invalidated by.
KEPT_BOTH_ROUTE: Final = f"{API_PREFIX}/conflicts"


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
        """Twenty-five rows, which is what section 10 states. Asserted so a row cannot be
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
        three and the ticket that owes each.
        """
        body = module_source(trigger.module)

        assert any(spelling in body for spelling in BUMPS_A_VERSION), trigger.row

    def test_a_row_with_no_module_is_one_whose_endpoint_does_not_exist(self) -> None:
        """The three rows the walk above cannot read, named rather than skipped.

        Each bumps according to the table and has nothing in the tree to read it from, because the
        endpoint has not been built: two approvals and the pin. Naming them here means the set is
        asserted rather than reported once per run as a skip nobody reads.
        """
        unreadable = {
            one.row: one.owner for one in TRIGGER_TABLE if one.module is None and one.bumps
        }

        assert unreadable == {
            "pin, unpin, drag, keyboard move": "41",
            "tradeoff approved": "42",
            "proposal approved": "42",
        }

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
        assert trigger.module is not None
        body = module_source(trigger.module)

        assert REQUESTS_A_SOLVE in body, trigger.row

    @pytest.mark.parametrize(
        "trigger",
        [one for one in TRIGGER_TABLE if not one.solves and one.module is not None],
        ids=lambda one: one.row,
    )
    def test_a_row_that_never_solves_is_a_row_that_changes_no_plan_input(
        self, trigger: Trigger
    ) -> None:
        # `kept-both` is the whole of this set among the wired rows. The two approval rows bump and
        # do not solve, and they belong to ticket 42, so they carry an owner rather than a module.
        assert trigger.row == "conflict resolved as kept-both"

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
    """Sixteen rows ask for a solve and reach none. Named here so the gap is countable.

    Building this enumeration is what made them visible, and BOTH directions are guarded, which is
    what makes the table's own claim true: a row that loses its bump fails the walk above, and a row
    that gains its solve request without losing its owner here fails
    ``test_a_row_that_still_names_an_owner_has_not_been_wired``. Without that second half the
    enumeration could not see the one change it exists to track, so it would have gone stale in
    exactly the direction the next ticket travels.
    """

    def test_the_unwired_count_is_what_the_walk_found(self) -> None:
        """Sixteen rows ask for a solve and reach none.

        Fifteen of them are mutations a person makes. The sixteenth is the horizon maintainer, which
        is not a mutation at all, because time passing is what triggers it, and which materializes
        instead of solving: that is ticket 1400.
        """
        unwired = [one for one in TRIGGER_TABLE if one.solves and one.owner is not None]
        by_a_person = [one for one in unwired if one.owner != "1400"]

        assert len(unwired) == 16
        assert len(by_a_person) == 15

    @pytest.mark.parametrize(
        "trigger",
        [one for one in TRIGGER_TABLE if one.owner is not None and one.module is not None],
        ids=lambda one: one.row,
    )
    def test_a_row_that_still_names_an_owner_has_not_been_wired(self, trigger: Trigger) -> None:
        """The reverse guard, and the direction the next ticket over this area actually travels.

        A row loses its owner when it gains its request, and this is what forces the pair to move
        together: wiring one without editing the table fails here, so the enumeration cannot report
        a gap that has been closed. It is the same pattern ``OUTSIDE_THE_RULE`` already has one
        screen down, applied to the half that was missing it.
        """
        body = module_source(trigger.module)

        assert REQUESTS_A_SOLVE not in body, (
            f"{trigger.module} now requests a solve, so the {trigger.row!r} row is wired: drop its "
            f"owner ({trigger.owner}) from TRIGGER_TABLE, and correct the counts beside it."
        )

    def test_every_unwired_row_names_a_ticket(self) -> None:
        for one in TRIGGER_TABLE:
            if one.owner is None:
                continue
            assert one.owner in {"41", "42", "1400", "1403"}, one.row

    def test_only_four_rows_reach_the_coordinator_today(self) -> None:
        # The four live triggers, one of which bypasses the debounce by design. The burst of pins
        # the window was measured against is row one, which is ticket 41's.
        wired = [one.row for one in TRIGGER_TABLE if one.solves and one.owner is None]

        assert sorted(wired) == [
            "conflict resolved as moved or retyped",
            "re-solve control",
            "tradeoff requested",
            "week adjustment revoked",
        ]

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
            if one.package not in bumping and not one.path.startswith(KEPT_BOTH_ROUTE)
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
        bumping set and it is not the allowlist member, so the rule has to report it.
        """
        invented = MutatingRoute("POST", f"{API_PREFIX}/widgets", "widgets")

        assert invented.package not in packages_that_bump()
        assert not invented.path.startswith(KEPT_BOTH_ROUTE)

    def test_every_package_that_bumps_is_named_by_a_row_of_the_table(self) -> None:
        """The other direction, so the table and the tree are crossed rather than read separately.

        A package that bumps and appears in no row is a mutation section 10 does not describe, which
        is either a missing row or a bump nothing asked for. ``solving`` is the one exception and it
        is not a trigger: the solve dispatch bumps because its own adoption changed the live plan.
        """
        named = {one.module.split("/")[0] for one in TRIGGER_TABLE if one.module is not None}

        assert packages_that_bump() - named - {"solving"} == set()

    def test_the_allowlist_holds_exactly_one_route(self, settings: ServiceSettings) -> None:
        # Section 10 puts one row in it: `kept-both`, which records a decision and changes neither a
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

    @pytest.mark.parametrize("prefix", list(OUTSIDE_THE_RULE), ids=lambda one: one)
    def test_every_exclusion_still_names_routes_that_exist(
        self, prefix: str, settings: ServiceSettings
    ) -> None:
        """So an exclusion cannot outlive what it was written for and quietly widen the hole."""
        every = {path for _method, path in api_route_pairs(settings)}

        assert any(path.startswith(prefix) for path in every), prefix
