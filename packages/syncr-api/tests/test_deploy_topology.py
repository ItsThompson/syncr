"""The deployed topology, read from the Compose files the deployment actually composes.

Five claims a machine can check, and every one of them is a property the ticket states rather than a
style preference:

- **The tunnel is the only ingress.** No service in the deployed stack publishes a host port.
- **The database is not routable from outside the host.** `data-net` is `internal: true`, and the
  set of services on it is bounded and declared.
- **Every image is pinned by digest.** Literally for a third-party image, and by a variable with no
  default for the four this repository builds, so a missing digest ABORTS compose rather than
  floating to `latest`.
- **Every service declares a memory limit**, and each matches section 19's resource budget.
- **The nightly one-shots are not resident**, so nothing that should run once a day is a service.

READ FROM `docker compose config` RATHER THAN FROM THE FILES. That is the resolved form, with
overlays merged, variables interpolated, anchors expanded and profile-gated services included, which
is the shape the deployment runs. A reader over the YAML source would answer about a file rather
than about a stack, and every claim above is about the stack. It is also the only reading that sees
a service a later overlay added.

`docker` is required for that, so the whole module skips without it, in the same way the integration
tier skips without a database.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import TYPE_CHECKING, Any, Final

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

from tests.test_alert_rules import repo_root

pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None, reason="the resolved Compose configuration needs the docker CLI"
)

# Every file a production stack composes, in order. `docker-compose.dev.yml` is deliberately absent:
# it is the one overlay that publishes ports, and it is never composed with these.
DEPLOYED_FILES: Final = (
    "docker-compose.yml",
    "docker-compose.monitoring.yml",
    "docker-compose.deploy.yml",
    "docker-compose.tunnel.yml",
)

# Placeholders for the four digests and the tunnel token, so the configuration resolves at all.
# Their ABSENCE is asserted separately: the deploy overlay uses the `:?` form, which aborts.
REQUIRED_VARIABLES: Final = {
    "SYNCR_API_DIGEST": "ghcr.io/owner/syncr-api@sha256:" + "a" * 64,
    "SYNCR_FRONTEND_DIGEST": "ghcr.io/owner/syncr-frontend@sha256:" + "b" * 64,
    "SYNCR_LEARNING_DIGEST": "ghcr.io/owner/syncr-learning@sha256:" + "c" * 64,
    "SYNCR_OPS_DIGEST": "ghcr.io/owner/syncr-ops@sha256:" + "d" * 64,
    "CLOUDFLARE_TUNNEL_TOKEN": "a-token-shaped-string",
}

# Section 19's resource budget, service by service. The limits live in the BASE file rather than the
# deploy overlay, deliberately: a limit that exists only in production is a limit nobody has watched
# work.
MEMORY_LIMITS: Final[Mapping[str, str]] = {
    "postgres": "2048M",
    "api": "768M",
    "worker": "768M",
    "prometheus": "768M",
    "grafana": "512M",
    "alertmanager": "128M",
    "frontend": "128M",
    "cloudflared": "128M",
    "learning": "1536M",
    # Not in section 19's table, which names the nine above. Each of these is a small resident
    # process or a one-shot, and each carries a limit for the same reason the nine do.
    "node_exporter": "128M",
    "cadvisor": "256M",
    "postgres_exporter": "128M",
    "ops": "512M",
    "fingerprint": "768M",
}

# WHO MAY REACH THE DATABASE. The ticket names three, and the fourth is declared with its reason:
# the exporter is the only monitoring service that talks to Postgres, and Postgres is reachable from
# nowhere else, so its scrape target has to sit on the same network.
DATA_NET_SERVICES: Final[Mapping[str, str]] = {
    "api": "the request path, and every repository read",
    "worker": "the plan pipeline, the projection and the calendar polling",
    "learning": "the nightly fitter, reading the outcome log",
    "postgres": "the database itself, and this is the only network it joins",
    "postgres_exporter": (
        "the only monitoring service that talks to Postgres. `pg_up` is what DatabaseUnreachable "
        "is stated over, and there is no other route to the server"
    ),
    "ops": "the backup path: pg_dump, pg_restore and the two psql readings",
    "fingerprint": "the reading a restore is checked against",
}

# The services that must not be resident. Each is work that happens on a schedule, and a service
# that restarts them would hold their memory all day: the fitter alone is ~800 MB while running.
ONE_SHOTS: Final = ("learning", "ops", "fingerprint")

# Every third-party image the deploy overlay pins LITERALLY, with the tag each digest was read from.
# An exact list rather than a count, so a pin that goes missing while another is added is visible.
THIRD_PARTY_TAGS: Final = (
    "postgres:16.10-bookworm",
    "prom/prometheus:v3.1.0",
    "prom/alertmanager:v0.28.0",
    "grafana/grafana:11.5.1",
    "prom/node-exporter:v1.8.2",
    "gcr.io/cadvisor/cadvisor:v0.52.1",
    "prometheuscommunity/postgres-exporter:v0.16.0",
)


def resolved(
    *files: str,
    profiles: tuple[str, ...] = ("ops", "scheduled"),
    digests: bool = True,
) -> dict[str, Any]:
    """The deployed configuration, as Compose resolves it.

    EVERY PROFILE, because `docker compose config` omits a profile-gated service entirely and three
    of the deployed services are gated. Without them the set this module reads is not the set it
    claims to bound, which is this repository's most repeated defect.

    ``digests`` stands in for the release `just deploy` records on the host. With it false, this is
    a machine that has never deployed, which is the state `just drill-local` runs in.
    """
    completed = _compose_config(*files, profiles=profiles, digests=digests)
    assert completed.returncode == 0, completed.stderr
    parsed: dict[str, Any] = json.loads(completed.stdout)
    return parsed


def _compose_config(
    *files: str,
    profiles: tuple[str, ...] = ("ops", "scheduled"),
    digests: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run `docker compose config` over these files, with or without a recorded release.

    `docker` is resolved from the PATH this declares, which a developer and CI both have; an
    absolute path would differ between the two.
    """
    command = ["docker", "compose"]
    for name in files:
        command += ["-f", name]
    for profile in profiles:
        command += ["--profile", profile]
    command += ["config", "--format", "json"]
    environ = {"PATH": "/usr/bin:/bin:/usr/local/bin"}
    return subprocess.run(  # noqa: S603 - a fixed argv, and no shell
        command,
        cwd=repo_root(),
        env={**REQUIRED_VARIABLES, **environ} if digests else environ,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="module")
def deployed() -> dict[str, Any]:
    return resolved(*DEPLOYED_FILES)


def services(configuration: dict[str, Any]) -> dict[str, Any]:
    found: dict[str, Any] = configuration["services"]
    return found


def published_ports(configuration: dict[str, Any]) -> Iterator[tuple[str, Any]]:
    for name, service in services(configuration).items():
        for port in service.get("ports", ()):
            yield name, port


class TestTheTunnelIsTheOnlyIngress:
    """No host ports. Discovering the hostname reaches an authenticated application and nothing."""

    def test_no_deployed_service_publishes_a_host_port(self, deployed: dict[str, Any]) -> None:
        assert list(published_ports(deployed)) == []

    def test_the_reading_would_see_one(self) -> None:
        """The positive control. The dev overlay publishes two, and this reads them."""
        development = resolved("docker-compose.yml", "docker-compose.dev.yml")

        assert {name for name, _ in published_ports(development)} == {"api", "postgres"}

    def test_the_tunnel_is_the_service_that_reaches_the_internet(
        self, deployed: dict[str, Any]
    ) -> None:
        cloudflared = services(deployed)["cloudflared"]

        assert "--no-autoupdate" in cloudflared["command"]
        assert cloudflared["networks"] == {"app-net": None}

    def test_the_tunnel_token_has_no_default(self) -> None:
        """A container retrying forever with an empty argument is worse than a deploy that stops."""
        assert "CLOUDFLARE_TUNNEL_TOKEN:?" in _text("docker-compose.tunnel.yml")


class TestTheDatabaseIsNotRoutable:
    """A leaked credential is not remotely exploitable, which is the mitigation section 19 names."""

    def test_data_net_is_internal(self, deployed: dict[str, Any]) -> None:
        assert deployed["networks"]["data-net"]["internal"] is True

    def test_only_the_declared_services_join_it(self, deployed: dict[str, Any]) -> None:
        """An exact equality, so a service added to that network needs a reason written here."""
        joined = {
            name
            for name, service in services(deployed).items()
            if "data-net" in (service.get("networks") or {})
        }

        assert joined == set(DATA_NET_SERVICES)

    @pytest.mark.parametrize("name", sorted(DATA_NET_SERVICES))
    def test_each_states_why_it_is_there(self, name: str) -> None:
        assert len(DATA_NET_SERVICES[name]) > 30

    def test_postgres_joins_nothing_else(self, deployed: dict[str, Any]) -> None:
        assert services(deployed)["postgres"]["networks"] == {"data-net": None}

    def test_the_dev_overlay_is_the_only_thing_that_lifts_the_isolation(self) -> None:
        """And it lifts it in the overlay rather than in the base file, which is the whole point."""
        development = resolved("docker-compose.yml", "docker-compose.dev.yml")

        assert development["networks"]["data-net"].get("internal", False) is False


class TestEveryImageIsPinned:
    """A floating tag makes a redeploy an unreviewed change, and a rollback impossible to name."""

    def test_every_deployed_image_is_a_digest(self, deployed: dict[str, Any]) -> None:
        unpinned = {
            name: service["image"]
            for name, service in services(deployed).items()
            if "@sha256:" not in service["image"]
        }

        assert unpinned == {}

    def test_our_own_images_have_no_default_so_a_missing_digest_aborts(self) -> None:
        """`:?` rather than `:-`. An empty value would resolve to a bare registry path."""
        overlay = _text("docker-compose.deploy.yml")

        for variable in ("SYNCR_API_DIGEST", "SYNCR_FRONTEND_DIGEST", "SYNCR_LEARNING_DIGEST"):
            assert f"${{{variable}:?" in overlay

    def test_a_deploy_without_the_digest_file_refuses(self) -> None:
        """The reading that proves the `:?` form does what the comment says it does."""
        completed = _compose_config(
            "docker-compose.yml", "docker-compose.deploy.yml", profiles=(), digests=False
        )

        assert completed.returncode != 0
        # WHICH variable it names is Compose's own iteration order over the services, so this
        # asserts the shape rather than a name: the first draft asserted `SYNCR_API_DIGEST` and
        # passed alone while failing in the module, because that run named the learning image.
        assert "is missing a value" in completed.stderr
        assert "DIGEST" in completed.stderr
        assert "a deploy never floats a tag" in completed.stderr

    def test_the_api_and_the_worker_are_one_image(self, deployed: dict[str, Any]) -> None:
        """Two entrypoints, one build. Separate digests would allow a stack from two commits."""
        found = services(deployed)

        assert found["api"]["image"] == found["worker"]["image"]
        assert found["fingerprint"]["image"] == found["api"]["image"]

    def test_the_third_party_digests_are_literal(self) -> None:
        """Knowable now, so reviewed here, with the tag beside each one.

        An EXACT count over an enumerated list, in the style `MEMORY_LIMITS` and `DATA_NET_SERVICES`
        use: a `>=` stops noticing when one pin goes missing and another is added.
        """
        overlay = _text("docker-compose.deploy.yml")

        for tag in THIRD_PARTY_TAGS:
            assert f"# {tag}" in overlay, tag
        assert overlay.count("@sha256:") == len(THIRD_PARTY_TAGS)


class TestTheDrillRunsWhatProductionRuns:
    """A drill that restored into a host-built image would prove the backup against something else.

    The reviewer's finding, and it was invisible until the configuration was RESOLVED: every human
    invocation of the ops and drill recipes composed the base file alone, which names
    `syncr-api:latest` and `syncr-ops:latest`. A digest pull creates no such tag, and both files
    carry a `build:` section, so the deployed host would have BUILT the images from its checkout:
    at step 11 of the first deployment, which is the criterion the epic cannot waive.
    """

    # The drill's own three, plus the two ops one-shots the recipes run. None is in section 19's
    # resource table and all five must resolve the release's digests on a host.
    DRILL_SERVICES = (
        "ops",
        "fingerprint",
        "api-restore",
        "fingerprint-restore",
        "postgres-restore",
    )

    DRILL_FILES = ("docker-compose.yml", "docker-compose.restore.yml", "docker-compose.deploy.yml")
    LOCAL_FILES = (
        "docker-compose.yml",
        "docker-compose.restore.yml",
        "docker-compose.drill-local.yml",
    )

    def test_every_drill_service_resolves_a_digest_on_a_host(self) -> None:
        """With the release recorded, which is the state `just deploy` leaves the host in."""
        found = services(resolved(*self.DRILL_FILES))

        for name in self.DRILL_SERVICES:
            assert "@sha256:" in found[name]["image"], name

    def test_the_drill_aborts_on_a_host_with_no_recorded_release(self) -> None:
        """Rather than building one.

        The requirement lives in the deploy overlay, and this is why the drill composes it:
        interpolation happens per file BEFORE merging, so a requirement inside
        `docker-compose.restore.yml` would fire for `just drill-local` too, which has no digests.
        """
        completed = _compose_config(*self.DRILL_FILES, digests=False)

        assert completed.returncode != 0
        assert "is missing a value" in completed.stderr

    def test_the_local_drill_resolves_without_a_release(self) -> None:
        """And this is what makes the instrument runnable: `just drill-local` composes no pins."""
        found = services(resolved(*self.LOCAL_FILES, digests=False))

        for name in ("ops", "fingerprint", "api-restore", "fingerprint-restore"):
            assert found[name]["image"].endswith(":latest"), name

    def test_the_scratch_database_is_the_digest_production_pins(self) -> None:
        """`docker-compose.restore.yml` claims it runs the same Postgres. This reads that claim."""
        deployed = services(resolved(*DEPLOYED_FILES))["postgres"]["image"]
        scratch = services(resolved(*self.DRILL_FILES))["postgres-restore"]["image"]

        assert scratch == deployed

    def test_the_drill_never_composes_the_tunnel(self) -> None:
        """A drill has no business being reachable."""
        assert "cloudflared" not in services(resolved(*self.DRILL_FILES))


class TestTheResourceBudget:
    """A leak shows as a restart against a known bound rather than as host-wide pressure."""

    def test_every_deployed_service_declares_a_memory_limit(self, deployed: dict[str, Any]) -> None:
        assert set(services(deployed)) == set(MEMORY_LIMITS)

    @pytest.mark.parametrize(("name", "limit"), sorted(MEMORY_LIMITS.items()))
    def test_each_limit_is_the_one_the_budget_states(
        self, deployed: dict[str, Any], name: str, limit: str
    ) -> None:
        stated = services(deployed)[name]["deploy"]["resources"]["limits"]["memory"]

        assert stated == _bytes(limit)

    def test_the_steady_state_fits_the_host(self, deployed: dict[str, Any]) -> None:
        """8 GB, and section 19 budgets ~3.3 GB resident. The LIMITS may oversubscribe; the RESIDENT
        set is what has to fit, so this asserts the one thing a configuration can: that the services
        which are always running do not declare more than the host has."""
        resident = sum(
            _as_bytes(service["deploy"]["resources"]["limits"]["memory"])
            for name, service in services(deployed).items()
            if name not in ONE_SHOTS
        )

        assert resident < 8 * 1024**3


class TestTheOneShots:
    """Work that happens on a schedule is not a service."""

    @pytest.mark.parametrize("name", ONE_SHOTS)
    def test_it_does_not_restart(self, deployed: dict[str, Any], name: str) -> None:
        assert services(deployed)[name]["restart"] == "no"

    @pytest.mark.parametrize("name", ONE_SHOTS)
    def test_it_is_gated_behind_a_profile_so_up_never_starts_it(
        self, deployed: dict[str, Any], name: str
    ) -> None:
        assert services(deployed)[name]["profiles"]

    def test_up_without_a_profile_starts_neither(self) -> None:
        """The positive control for the gating: the resolved set without profiles omits all."""
        without = resolved(*DEPLOYED_FILES, profiles=())

        assert set(ONE_SHOTS) & set(services(without)) == set()

    def test_the_resident_services_do_restart(self, deployed: dict[str, Any]) -> None:
        for name, service in services(deployed).items():
            if name in ONE_SHOTS:
                continue
            assert service["restart"] == "unless-stopped", name


class TestMigrationsAndArchiving:
    """Two properties of the database service the recovery objectives rest on."""

    def test_wal_archiving_is_configured_in_the_base_file(self, deployed: dict[str, Any]) -> None:
        command = " ".join(services(deployed)["postgres"]["command"])

        assert "wal_level=replica" in command
        assert "archive_mode=on" in command
        assert "/wal-archive/%f" in command

    def test_the_archive_timeout_is_the_one_the_recovery_point_is_stated_over(
        self, deployed: dict[str, Any]
    ) -> None:
        """The figure lives in `ops.config`, and this is where Postgres is told it."""
        from ops.config import ARCHIVE_TIMEOUT_SECONDS

        command = " ".join(services(deployed)["postgres"]["command"])

        assert f"archive_timeout={ARCHIVE_TIMEOUT_SECONDS}" in command

    def test_no_service_runs_migrations_at_startup(self, deployed: dict[str, Any]) -> None:
        """They run as a one-shot before api and worker start, so two replicas cannot race."""
        for name, service in services(deployed).items():
            command = " ".join(service.get("command") or ())
            assert "alembic upgrade" not in command, name

    def test_the_api_readiness_check_is_readyz(self, deployed: dict[str, Any]) -> None:
        """`/readyz` compares the applied revision against the head the checkout ships."""
        test = " ".join(services(deployed)["api"]["healthcheck"]["test"])

        assert "/readyz" in test


class TestTheFrontendServesOneOrigin:
    """The session cookie is `SameSite=Lax` and every unsafe method is behind an origin check."""

    def test_caddy_proxies_the_api_paths(self) -> None:
        directives = _caddy_directives()

        for prefix in ("/api/*", "/auth/*", "/oauth/*", "/.well-known/*", "/healthz", "/readyz"):
            assert prefix in directives

    def test_it_does_not_proxy_the_metrics_exposition(self) -> None:
        """Section 18: `/metrics` is reachable only inside `app-net`. Proxying it would publish
        every figure about the user's own plan through the tunnel.

        READ OVER THE DIRECTIVES, NOT THE FILE. The first version of this read the whole text and
        failed on the COMMENT that explains the absence, which is the same defect as a guard reading
        a set it does not mean: what must not carry `/metrics` is the configuration.
        """
        assert "/metrics" not in _caddy_directives()

    def test_the_reading_would_see_a_proxied_path(self) -> None:
        """The positive control: the directives it reads are the ones that matter."""
        assert "reverse_proxy api:8000" in _caddy_directives()

    def test_the_proxied_prefixes_are_the_ones_development_proxies(self) -> None:
        """One list, two places, and a drift between them is a route that works in only one."""
        directives = _caddy_directives()
        vite = _text("frontend/vite.config.ts")
        declared = vite.partition("proxiedPrefixes = [")[2].partition("]")[0]

        for prefix in [one.strip().strip('"') for one in declared.split(",") if one.strip()]:
            assert prefix in directives, prefix


def _text(relative: str) -> str:
    return (repo_root() / relative).read_text(encoding="utf-8")


def _caddy_directives() -> str:
    """The Caddyfile with its comments removed, which is what Caddy acts on."""
    return "\n".join(
        line
        for line in _text("frontend/Caddyfile").splitlines()
        if not line.strip().startswith("#")
    )


def _bytes(stated: str) -> str:
    """Compose renders a memory limit in bytes, and the budget is written in mebibytes."""
    return str(_as_bytes(stated))


def _as_bytes(stated: str | int) -> int:
    if isinstance(stated, int):
        return stated
    if stated.endswith("M"):
        return int(stated[:-1]) * 1024**2
    return int(stated)
