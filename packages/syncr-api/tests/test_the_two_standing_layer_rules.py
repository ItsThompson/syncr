"""The two standing layer rules of this api, and a control apiece proving each can fail.

R1: ``app_factory.py`` is the only file under ``core`` that may import a feature package. It is
the composition root: assembling the routers the feature-router registry names is its one job,
and the moment any other core module reaches into a feature, core stops being the layer every
feature stands on and becomes a participant in whatever cycle the reach closes. The rule reads
the registry itself, so its justification stays attached to what the factory file really
imports rather than to a list someone maintains by hand.

R3: besides ``oauth``, ``accounts`` reaches exactly one feature module, ``learned.repository``,
and only from ``bootstrap.py`` and ``provisioning.py``. The reason travels with the rule:
provisioning seeds weight-set version 1 inside the same transaction that creates the tenant,
so a new tenant's weight sets exist before anything can ask for them. Any second direction out
of ``accounts`` would put account lifecycle under another feature's rules.

Both rules are readings of the source as text, so each is checked against the real tree AND
against a synthetic tree carrying a planted violation: a reading that was never seen to fail
cannot be trusted to fail when the thing it guards arrives.

The walk also records how large the dependency graph stands: packages, directed inter-package
edges, feature-to-feature pairs that import each other, and how many of those pairs involve
``plans``. These are derived here on every run, never restated from prose. A figure that moves
means some import changed direction on purpose, so the recorded figure changes in that same
change. No claim is made that the graph is acyclic: many pairs do cycle, they are counted
rather than blessed, and asserting their absence would be false on the first run.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import syncr_api
from tests.layer_census import (
    API_PACKAGE_ROOT,
    CORE_PACKAGE,
    CrossImport,
    core_feature_importers,
    cross_imports,
    declared_packages,
    mutual_import_pairs,
    package_edges,
    registry_factory_origins,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

# The real tree both rules stand over, resolved from the installed module rather than the cwd.
SOURCE_ROOT = Path(syncr_api.__file__).resolve().parent
APP_FACTORY = SOURCE_ROOT / "core" / "app_factory.py"

ACCOUNTS_PACKAGE = "accounts"
OAUTH_PACKAGE = "oauth"
PLANS_PACKAGE = "plans"
LEARNED_REPOSITORY = "learned.repository"

# The one importer R1 allows, and the only feature directions out of accounts beyond oauth that
# R3 allows. Each entry pairs the reached module with the file that reaches it, so the reason a
# file may import across stays checkable against where the import actually sits.
THE_APP_FACTORY = "core/app_factory.py"
REACHED_BEYOND_OAUTH = frozenset(
    {
        (LEARNED_REPOSITORY, f"{ACCOUNTS_PACKAGE}/bootstrap.py"),
        (LEARNED_REPOSITORY, f"{ACCOUNTS_PACKAGE}/provisioning.py"),
    }
)

# What the walk measures against today's tree. Edges count every unique directed import between
# two distinct packages, core included; cycles count the feature-to-feature pairs importing in
# both directions, one apiece. When one moves, an edge moved with it: find that import, decide
# whether it belongs, and record the new figure here in the change that caused it.
MEASURED_PACKAGES = 32
MEASURED_EDGES = 242
MEASURED_MUTUAL_PAIRS = 32
MUTUAL_PAIRS_PLANS_SITS_IN = 17


def test_r1_only_the_app_factory_imports_a_feature_package() -> None:
    imports = cross_imports(SOURCE_ROOT)
    assert core_feature_importers(imports) == {THE_APP_FACTORY}
    # The registry justifies that one importer, so it has to resolve: every factory it names
    # must be bound by an import in the factory file, aimed at a feature package. A registry
    # naming anything unimported, or anything in core, means the reading above is anchored to
    # nothing and the rule has gone quiet.
    origins = registry_factory_origins(APP_FACTORY)
    assert origins, "the router registry named no factories"
    factory_imports = {crossed.target for crossed in imports if crossed.importer == THE_APP_FACTORY}
    for origin in origins.values():
        assert origin in factory_imports
        assert not origin.startswith(f"{API_PACKAGE_ROOT}.{CORE_PACKAGE}.")


def test_r1_control_a_feature_import_planted_in_another_core_module_bites(tmp_path: Path) -> None:
    planted = "core/clock.py"
    root = _plant(
        tmp_path,
        {
            THE_APP_FACTORY: "",
            planted: f"from {API_PACKAGE_ROOT}.{PLANS_PACKAGE}.wiring import build_weeks_router\n",
            f"{PLANS_PACKAGE}/wiring.py": "",
        },
    )
    assert core_feature_importers(cross_imports(root)) == {planted}


def test_r3_accounts_reaches_learned_repository_and_nothing_else_beyond_oauth() -> None:
    assert _reached_beyond_oauth(cross_imports(SOURCE_ROOT)) == REACHED_BEYOND_OAUTH


def test_r3_control_a_second_reach_out_of_accounts_bites(tmp_path: Path) -> None:
    planted = ("plans.models", "accounts/service.py")
    root = _plant(
        tmp_path,
        {
            "accounts/bootstrap.py": (
                f"from {API_PACKAGE_ROOT}.{LEARNED_REPOSITORY} import WeightSetRepository\n"
            ),
            "accounts/service.py": f"from {API_PACKAGE_ROOT}.{planted[0]} import WeekPlan\n",
            "learned/repository.py": "",
            "plans/models.py": "",
        },
    )
    reached = _reached_beyond_oauth(cross_imports(root))
    assert planted in reached
    assert reached - REACHED_BEYOND_OAUTH == {planted}


def test_the_walk_records_the_graph_figures_it_measures() -> None:
    packages = declared_packages(SOURCE_ROOT)
    edges = package_edges(cross_imports(SOURCE_ROOT))
    mutual_pairs = mutual_import_pairs(edges)
    assert len(packages) == MEASURED_PACKAGES
    assert len(edges) == MEASURED_EDGES
    assert len(mutual_pairs) == MEASURED_MUTUAL_PAIRS
    plans_pairs = sum(1 for pair in mutual_pairs if PLANS_PACKAGE in pair)
    assert plans_pairs == MUTUAL_PAIRS_PLANS_SITS_IN


def _reached_beyond_oauth(imports: frozenset[CrossImport]) -> frozenset[tuple[str, str]]:
    """Where accounts reaches into other features, as (module reached, importing file)."""
    api_prefix = f"{API_PACKAGE_ROOT}."
    outside = (f"{api_prefix}{OAUTH_PACKAGE}.", f"{api_prefix}{CORE_PACKAGE}.")
    return frozenset(
        (crossed.target.removeprefix(api_prefix), crossed.importer)
        for crossed in imports
        if crossed.source_package == ACCOUNTS_PACKAGE and not crossed.target.startswith(outside)
    )


def _plant(root: Path, modules: Mapping[str, str]) -> Path:
    """A synthetic source root shaped like the api's, carrying exactly these modules."""
    for relative, source in modules.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return root
