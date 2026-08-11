"""The container-log bound, read from the three Compose files that declare it.

Docker's `json-file` driver keeps a container's log until the disk is full. Each deployed Compose
file declares one anchor that bounds it, and this module reads four things about those declarations:

- **Every service a file declares reaches that file's anchor.** The service set is DERIVED from the
  file's own `services:` mapping rather than listed here, so a service added tomorrow is inside this
  reading the moment it exists, and no service can be dropped from it by being renamed.
- **The bound is stated once per file.** One anchor definition, and the values appear nowhere else
  in the file, so "this service is bounded differently from its neighbour" is not expressible.
- **The three files agree.** A YAML anchor does not cross files, so the bound is written three
  times, which is three chances to change one and two files that would keep the old figure.
- **The arithmetic recorded beside the bound reproduces.** The figures the base file states are
  crossed against the services these files declare and against the anchor's own values, so a service
  added without a thought for the disk fails here rather than being absorbed silently.

READ OVER THE YAML SOURCE, AND NOTHING HERE RUNS DOCKER OR STARTS A CONTAINER. What the RESOLVED
configuration carries is a different claim about a different subject: this module answers about the
files, which one states the bound, whether each states it once, and whether the three agree.

WHAT THIS READING CANNOT SEE, stated because a guard credited with more reach than it has is worse
than no guard: it reads three named files, so a fourth deployed Compose file declaring an unbounded
service is outside it. `TestTheReadingSeesEveryDeployedService` is what closes that: the services
these three files declare must be exactly the ones the deployed memory budget carries, and that
budget is asserted equal to the resolved stack's own service set in `test_deploy_topology.py`, which
needs the docker CLI. Where docker is absent that crossing is against a hand-written list, and it
proves agreement with the budget rather than with the stack.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

import pytest

from tests.test_alert_rules import repo_root
from tests.test_deploy_topology import MEMORY_LIMITS

if TYPE_CHECKING:
    from collections.abc import Mapping

# The files that declare the bound. `docker-compose.deploy.yml` repins digests and states no policy,
# and `docker-compose.dev.yml` is never composed with the deployed set; the dev stack inherits the
# base file's anchor, which is the same reason the memory limits live there.
DECLARING_FILES: Final = (
    "docker-compose.yml",
    "docker-compose.monitoring.yml",
    "docker-compose.tunnel.yml",
)

# The base file, and the one place the arithmetic behind the bound is written down.
ARITHMETIC: Final = DECLARING_FILES[0]

# The disk budget the arithmetic is stated against, whose own figure lives in this runbook.
DISK_RUNBOOK: Final = "docs/runbooks/disk-pressure.md"

# THE BOUND, WHICH IS A DECISION AND NOT A MEASUREMENT: no log on a real host has been watched
# growing. It is spelled once here, so a change to the shipped figures fails rather than passing
# quietly, and the other two files are then crossed against the base file rather than against a
# second copy of this mapping.
DECIDED: Final[Mapping[str, str]] = {
    "driver": "json-file",
    "max-size": "10m",
    "max-file": "3",
}

ANCHOR: Final = "x-log-bound: &log-bound"
ALIAS: Final = "logging: *log-bound"
ONE_SHOT: Final = 'restart: "no"'

# A service key: exactly two spaces of indent inside the `services:` mapping. Its own keys sit at
# four, and a comment between two services starts with `#`, so neither is read as a service.
_SERVICE: Final = re.compile(r"^ {2}(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]*):[ \t]*$")

# The anchor's leaves, in the quoted form the files write them in. Prose mentioning `max-size` sits
# behind a `#`, so this matches the declaration and not the paragraph explaining it.
_LEAF: Final = re.compile(r'^ +(?P<key>driver|max-size|max-file): "(?P<value>[^"]+)"$', re.M)

_PER_SERVICE: Final = re.compile(
    r"one service +(?P<size>\d+)m x (?P<rotations>\d+) rotations = (?P<footprint>\d+) MB"
)
_STACK: Final = re.compile(
    r"the stack +(?P<services>\d+) services x (?P<each>\d+) MB = (?P<total>\d+) MB, "
    r"about (?P<share>[\d.]+)% of the (?P<disk>\d+) GB disk"
)

MIB_PER_GIB: Final = 1024


def _text(relative: str) -> str:
    return (repo_root() / relative).read_text(encoding="utf-8")


def service_blocks(content: str) -> dict[str, list[str]]:
    """Every service the file declares, with the lines of its block, read from `services:` itself.

    The mapping ends at the next key in column one, which is how `networks:` and `volumes:` stay out
    of the answer. Comment lines are dropped: a comment is prose ABOUT a service rather than a key
    of one, and two comments in the base file mention `restart: "no"` while three mention the alias,
    so keeping them would put a neighbour's words into a service's block.
    """
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    inside = False
    for line in content.splitlines():
        if line.rstrip() == "services:":
            inside = True
            continue
        if not inside:
            continue
        if line.strip().startswith("#"):
            continue
        if line and not line.startswith((" ", "\t")):
            break
        found = _SERVICE.match(line)
        if found is not None:
            current = found["name"]
            blocks[current] = []
        elif current is not None:
            blocks[current].append(line)
    return blocks


def anchor_block(content: str) -> str:
    """The lines of the file's own anchor definition, which is where its values live."""
    _, marker, rest = content.partition(f"{ANCHOR}\n")
    assert marker, f"no `{ANCHOR}` definition, so there is nothing to read"
    lines: list[str] = []
    for line in rest.splitlines():
        if line and not line.startswith((" ", "\t")):
            break
        lines.append(line)
    return "\n".join(lines)


def declared_bound(content: str) -> dict[str, str]:
    return {found["key"]: found["value"] for found in _LEAF.finditer(anchor_block(content))}


def unbounded_services(content: str) -> list[str]:
    """Every service in the file that does not reach the file's anchor."""
    return sorted(
        name
        for name, lines in service_blocks(content).items()
        if not any(ALIAS in line for line in lines)
    )


def one_shot_services(content: str) -> list[str]:
    """Every service in the file that runs once rather than staying up.

    Derived from what the service declares, so no list of one-shot names exists here.
    """
    return sorted(
        name
        for name, lines in service_blocks(content).items()
        if any(ONE_SHOT in line for line in lines)
    )


def declared_services() -> set[str]:
    return {name for one in DECLARING_FILES for name in service_blocks(_text(one))}


class TestEveryServiceEachFileDeclaresIsBounded:
    """Derived from the file, so the reading covers a service nobody remembered to add to a list."""

    @pytest.mark.parametrize("name", DECLARING_FILES)
    def test_every_service_reaches_the_files_own_anchor(self, name: str) -> None:
        assert service_blocks(_text(name)), f"{name}: no services were read, so nothing is asserted"
        assert unbounded_services(_text(name)) == []

    @pytest.mark.parametrize("name", DECLARING_FILES)
    def test_a_service_that_loses_the_alias_is_reported(self, name: str) -> None:
        """The negative control, per file: the reading distinguishes bounded from unbounded."""
        content = _text(name)
        without = content.replace(f"    {ALIAS}\n", "", 1)

        assert without != content, f"{name}: the alias was not found, so nothing was removed"
        assert len(unbounded_services(without)) == 1

    def test_the_one_shots_are_in_the_reading_rather_than_exempt(self) -> None:
        """A container that exited keeps its log, and a run that was not `--rm` keeps the container.

        Over the three files at once rather than one at a time, because two of them declare no
        one-shot at all and a per-file reading would assert nothing for those two while looking as
        though it did. The premise is asserted first: a reading that finds no one-shot anywhere has
        stopped seeing them, which is a failure rather than a pass.
        """
        found = {name: one_shot_services(_text(name)) for name in DECLARING_FILES}

        assert [name for names in found.values() for name in names], (
            "no file declares a one-shot, so this reading asserts nothing"
        )
        exempt = {
            name: sorted(set(names) & set(unbounded_services(_text(name))))
            for name, names in found.items()
            if set(names) & set(unbounded_services(_text(name)))
        }
        assert exempt == {}


class TestTheBoundIsStatedOncePerFile:
    """One anchor, and the figures nowhere else, so two services cannot be bounded differently."""

    @pytest.mark.parametrize("name", DECLARING_FILES)
    def test_the_file_defines_exactly_one_anchor(self, name: str) -> None:
        assert _text(name).count(ANCHOR) == 1

    @pytest.mark.parametrize("name", DECLARING_FILES)
    def test_the_values_are_written_only_inside_that_anchor(self, name: str) -> None:
        content = _text(name)

        assert len(_LEAF.findall(content)) == len(DECIDED)
        assert len(_LEAF.findall(anchor_block(content))) == len(DECIDED)


class TestTheThreeFilesAgree:
    """An anchor does not cross a file boundary, so the same decision is written three times."""

    def test_the_base_file_declares_the_decided_bound(self) -> None:
        assert declared_bound(_text(ARITHMETIC)) == dict(DECIDED)

    @pytest.mark.parametrize("name", DECLARING_FILES[1:])
    def test_the_other_files_declare_what_the_base_file_does(self, name: str) -> None:
        assert declared_bound(_text(name)) == declared_bound(_text(ARITHMETIC))

    def test_the_driver_is_named_rather_than_left_to_the_daemon(self) -> None:
        """`max-size` and `max-file` are options OF `json-file`. A host configured for `journald`
        takes both keys and bounds nothing, so the driver is part of the bound."""
        assert declared_bound(_text(ARITHMETIC))["driver"] == DECIDED["driver"]


class TestTheArithmeticReproduces:
    """Every figure recorded beside the bound, crossed against what produces it."""

    def test_the_per_service_footprint_is_the_anchors_own_values(self) -> None:
        stated = _PER_SERVICE.search(_text(ARITHMETIC))
        bound = declared_bound(_text(ARITHMETIC))

        assert stated is not None, "the per-service arithmetic is not recorded"
        assert f"{stated['size']}m" == bound["max-size"]
        assert stated["rotations"] == bound["max-file"]
        assert int(stated["footprint"]) == int(stated["size"]) * int(stated["rotations"])

    def test_the_stack_footprint_counts_the_services_these_files_declare(self) -> None:
        """The count is DERIVED here and stated there, so a service added without a thought for the
        disk reddens this rather than being absorbed."""
        stated = _STACK.search(_text(ARITHMETIC))
        per_service = _PER_SERVICE.search(_text(ARITHMETIC))

        assert stated is not None, "the stack arithmetic is not recorded"
        assert per_service is not None
        assert int(stated["services"]) == len(declared_services())
        assert stated["each"] == per_service["footprint"]
        assert int(stated["total"]) == int(stated["services"]) * int(stated["each"])

    def test_the_share_of_the_disk_is_the_quotient_it_claims_to_be(self) -> None:
        stated = _STACK.search(_text(ARITHMETIC))

        assert stated is not None
        share = int(stated["total"]) / (int(stated["disk"]) * MIB_PER_GIB) * 100
        assert round(share, 1) == float(stated["share"])

    def test_the_disk_is_the_one_the_runbook_states(self) -> None:
        """The budget's own figure lives in the runbook. This is the crossing that keeps the two
        readings of the same host from disagreeing."""
        stated = _STACK.search(_text(ARITHMETIC))

        assert stated is not None
        assert f"{stated['disk']} GB" in _text(DISK_RUNBOOK)

    def test_it_is_recorded_as_a_decision_rather_than_as_a_measurement(self) -> None:
        """A prose check, and it can see only the words. What it prevents is the sentence quietly
        becoming a claim about a host whose logs nobody has watched."""
        assert (
            "decision against the disk budget rather than a measurement"
            in _text(ARITHMETIC).lower()
        )

    @pytest.mark.parametrize("name", [*DECLARING_FILES[1:], DISK_RUNBOOK])
    def test_no_other_file_restates_the_arithmetic(self, name: str) -> None:
        """The runbook is in this reading, and it is the reason the reading exists.

        The disk budget lives there, so it is the obvious second home for these figures, and a
        second copy is a figure that gets updated in one place. Prose stating the bound itself
        passes: what may appear in only one file is the arithmetic, and it appears in the file that
        carries the anchor it explains.
        """
        assert _STACK.search(_text(name)) is None, (
            f"{name} restates the stack arithmetic, which {ARITHMETIC} records"
        )


class TestTheReadingSeesEveryDeployedService:
    """The one crossing that bounds this module's own file list.

    Three named files is a reading that a fourth file defeats. The services these three declare must
    be exactly the ones the deployed memory budget carries, and that budget is crossed against the
    resolved configuration's own service set where the docker CLI exists.
    """

    def test_the_services_these_files_declare_are_the_budgets_own(self) -> None:
        assert declared_services() == set(MEMORY_LIMITS)

    def test_the_reading_is_not_empty(self) -> None:
        assert len(declared_services()) > 1
