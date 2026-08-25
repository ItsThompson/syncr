"""The refusal of a re-picked pigment another Area already holds.

The service suite proves a re-pick works; this one proves what it must never produce: two
Areas on one step of the ramp. A refusal is asserted three ways, because each catches a
different weakening: that it names the Area holding the step (a caller has to know whom to
ask), that it says nothing was changed (a refused patch is not a half-applied one), and that
the rows are untouched.

The sequence test is the point of the suite. Refusal per request is the mechanism; the claim
is about every reachable state, so it is stated as a walk over operations rather than as one
hand-picked pair.
"""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from random import Random
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.areas.declarations import AreaChange, AreaDeclaration
from syncr_api.areas.schemas import _PIGMENT_DESCRIPTION
from syncr_api.areas.service import AreaService
from syncr_api.core.errors import Conflict, ValidationFailed
from syncr_api.core.patches import ABSENT
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import ALL_SCOPES
from syncr_api.user_settings.solve_inputs import BacklogWideBump
from syncr_domain.pigments import PIGMENT_COUNT
from tests.service_fakes import FakeAreaRepository, FakeSettingsRepository

if TYPE_CHECKING:
    from syncr_api.areas.records import AreaRecord

NOW = datetime(2026, 8, 2, 9, 0, tzinfo=UTC)


class RecordingWeekInputVersions:
    """Every range the service asked to have bumped, in order."""

    def __init__(self) -> None:
        self.bumped: list[object] = []

    async def bump(self, weeks: object) -> None:
        self.bumped.append(weeks)


@pytest.fixture
def principal() -> Principal:
    return Principal(tenant_id=uuid4(), user_id=uuid4(), scopes=ALL_SCOPES)


@pytest.fixture
def versions() -> RecordingWeekInputVersions:
    return RecordingWeekInputVersions()


def build_areas(
    principal: Principal,
    versions: RecordingWeekInputVersions,
) -> tuple[AreaService, FakeAreaRepository]:
    areas = FakeAreaRepository(principal.tenant_id)
    service = AreaService(
        areas=areas,
        bump=BacklogWideBump(
            versions=versions,
            settings=FakeSettingsRepository(principal.tenant_id),
        ),
        clock=lambda: NOW,
    )
    return service, areas


def a_declaration(name: str) -> AreaDeclaration:
    return AreaDeclaration(name=name, parent_id=None, budget_percent=None, floor_hours=None)


async def declare(service: AreaService, principal: Principal, name: str) -> AreaRecord:
    view = await service.create(principal, a_declaration(name))
    return view.area


def a_change(pigment_index: int) -> AreaChange:
    return AreaChange(ABSENT, pigment_index, ABSENT, ABSENT)


async def held_steps(areas: FakeAreaRepository) -> list[int]:
    return [row.pigment_index for row in await areas.list_all()]


# --------------------------------------------------------------------------------
# The refusal
# --------------------------------------------------------------------------------


async def test_a_patch_onto_a_step_another_area_holds_is_refused_and_changes_nothing(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, areas = build_areas(principal, versions)
    fitness = await declare(service, principal, "Fitness")
    career = await declare(service, principal, "Career")
    versions.bumped.clear()

    with pytest.raises(Conflict) as refused:
        await service.update(principal, career.id, a_change(fitness.pigment_index))

    # It names the Area that holds the step, and states that nothing was changed.
    assert "Fitness" in str(refused.value.detail)
    assert "Nothing was changed" in str(refused.value.detail)
    # Career still holds the step the deal dealt it.
    stored = {row.name: row.pigment_index for row in await areas.list_all()}
    assert stored["Career"] != fitness.pigment_index
    # Nothing was changed, so no solve input was invalidated either.
    assert versions.bumped == []


async def test_a_patch_onto_a_step_nobody_holds_still_succeeds(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The control at the accepted side of the rule: the ramp still has free steps, and moving
    # onto one of them is the freedom the field description promises.
    service, _ = build_areas(principal, versions)
    fitness = await declare(service, principal, "Fitness")
    career = await declare(service, principal, "Career")
    held = {fitness.pigment_index, career.pigment_index}
    free = next(index for index in range(PIGMENT_COUNT) if index not in held)

    changed = await service.update(principal, career.id, a_change(free))

    assert changed.area.pigment_index == free


async def test_re_picking_the_step_an_area_already_holds_is_not_an_error(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The other control: the rule excludes the row being changed, or no Area could ever be
    # patched without also moving its pigment.
    service, _ = build_areas(principal, versions)
    fitness = await declare(service, principal, "Fitness")

    changed = await service.update(principal, fitness.id, a_change(fitness.pigment_index))

    assert changed.area.pigment_index == fitness.pigment_index


# --------------------------------------------------------------------------------
# Every reachable state
# --------------------------------------------------------------------------------


async def test_no_patch_target_leaves_two_areas_on_one_step(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # Every target, from every Area: a success leaves the steps distinct, and a refusal names
    # the only condition that can refuse, another Area holding the target.
    service, areas = build_areas(principal, versions)
    declared = [await declare(service, principal, f"Area {index}") for index in range(4)]

    for mover in declared:
        original = mover.pigment_index
        for target in range(PIGMENT_COUNT):
            others_holding = any(
                area.pigment_index == target and area.id != mover.id for area in declared
            )
            if others_holding:
                with pytest.raises(Conflict) as refused:
                    await service.update(principal, mover.id, a_change(target))
                assert "Nothing was changed" in str(refused.value.detail)
            else:
                moved = await service.update(principal, mover.id, a_change(target))
                assert moved.area.pigment_index == target
            steps = await held_steps(areas)
            assert len(steps) == len(set(steps)), f"{mover.name} -> {target} shared a step"
            # Put the mover back, so the next attempt starts from the dealt state.
            await service.update(principal, mover.id, a_change(original))


@pytest.mark.parametrize("seed", [20260802, 20260803], ids=["walk a", "walk b"])
async def test_no_sequence_of_creates_and_patches_puts_two_areas_on_one_step(
    principal: Principal, versions: RecordingWeekInputVersions, seed: int
) -> None:
    # A walk over mixed creates and patches through the real service. Every refusal is left
    # refused and every acceptance applied; whatever the order, no step ends up shared. Two
    # seeds, because one walk is one path through the space of orders, not the space itself.
    rng = Random(seed)  # noqa: S311 - fixed walks of operations, not secrets
    service, areas = build_areas(principal, versions)

    for step in range(400):
        if rng.random() < 0.35:
            # A full ramp refuses; the walk continues.
            with suppress(ValidationFailed):
                await declare(service, principal, f"Area {step}")
        else:
            found = await areas.list_all()
            if found:
                mover = rng.choice(list(found))
                target = rng.randrange(PIGMENT_COUNT)
                # A shared step refuses; the walk continues.
                with suppress(Conflict):
                    await service.update(principal, mover.id, a_change(target))
        steps = await held_steps(areas)
        assert len(steps) == len(set(steps)), f"operation {step} left two Areas on one step"


# --------------------------------------------------------------------------------
# What the contract says
# --------------------------------------------------------------------------------


def test_the_field_description_qualifies_the_re_pick() -> None:
    # The description reaches the OpenAPI document, so the freedom it states is the freedom
    # the route enforces: a re-pick onto a step no other Area holds.
    assert "no other Area holds" in _PIGMENT_DESCRIPTION
