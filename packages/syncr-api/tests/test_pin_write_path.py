"""What one pin request does, in the order it does it, and which frame each consumer is handed.

Pure, no database. The assembler and the probe are the REAL instrumented ones, composed over the
week assembler's own fakes, so the two histograms are observed by the shipped code rather than by a
double. Storage is faked, and every fake records the call it was asked for, so the sequence these
tests assert is the sequence `PinService` performed.

Four claims, each of which a docstring in the pin write path states in prose:

1. One pin request takes TWO observations on the assembly histogram and one on the probe's.
2. The pair of labels those counts are read under is the pair `pins/injection.py` binds.
3. The price and the feature snapshot read the frame taken BEFORE the pin row exists.
4. The verdict reads the frame taken AFTER it, and the version is bumped between the two.

The pin's cost is priced by a second statement, so `pins.price` following the second assembly is
part of the order asserted here: a write that becomes one statement moves this expectation.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Any
from unittest.mock import patch
from uuid import uuid4

from syncr_api.areas.repository import AreaRepository
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import ALL_SCOPES
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.pins.costs import pin_price
from syncr_api.pins.declarations import PinRequested
from syncr_api.pins.features import edit_context
from syncr_api.pins.service import PinService
from syncr_api.plans.assembler import ASSEMBLY_DURATION, AssemblyCaller, WeekAssembler
from syncr_api.plans.edits import EditEventRepository
from syncr_api.plans.pins import PinRepository
from syncr_api.plans.placements import WeekPlacements
from syncr_api.plans.proposals import PendingProposalRepository
from syncr_api.plans.recording import VerdictRecorder
from syncr_api.plans.records import PinRecord, PlanRevisionRecord
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import stored_document
from syncr_api.plans.verdicts import PROBE_DURATION, ProbeCaller, WeekProbe
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.config import PENDING, SOLVE
from syncr_api.solving.coordinator import SolveCoordinator
from syncr_api.solving.records import OperationRecord
from syncr_api.tasks.repository import TaskRepository
from tests.assembly_fakes import (
    NOW,
    TENANT,
    WEEK,
    FakeAreas,
    FakeTasks,
    a_pin,
    a_plan,
    a_task,
    a_task_block,
    a_weight_set,
    an_area,
    an_assembler,
    at,
    between,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime
    from pathlib import Path

    from syncr_api.areas.records import AreaRecord
    from syncr_api.core.columns import JsonDocument
    from syncr_api.learned.records import WeightSetRecord
    from syncr_api.plans.declarations import EditToRecord, PinToHold
    from syncr_api.plans.records import VerdictEventRecord
    from syncr_api.tasks.records import TaskRecord
    from syncr_domain.feasibility import Verdict
    from syncr_domain.identifiers import AreaId, EditEventId, OperationId, PinId, TaskId
    from syncr_domain.intervals import Interval
    from syncr_domain.plan import PlanDocument
    from syncr_domain.weeks import IsoWeek
    from syncr_solver.inputs import SolveInputs, WeekAdjustment

# The two labels every figure in this module is read under. Asserted against the labels
# `pins/injection.py` binds, so a count taken here cannot be a count of a label production does not
# use.
ASSEMBLY_CALLER = AssemblyCaller.REQUEST
PROBE_CALLER = ProbeCaller.REQUEST

# One pin request's contribution to each histogram, which is the reading an operator sizing the
# request path takes the p95 from.
ASSEMBLIES_PER_PIN = 2.0
PROBES_PER_PIN = 1.0

CALLER_LABEL = "caller"

# The block the drive below pins, and where it is dragged to. Friday, so both intervals are in the
# part of the week `NOW` has not reached: a pin on a block that has begun is refused before any of
# this runs.
FRIDAY = 4
PROPOSED = between(10, 11, day=FRIDAY)
ACCEPTED = between(12, 13, day=FRIDAY)

# The task's deadline falls between the two placements, so the drag really costs something: the
# proposed placement meets it and the accepted one misses it. A move no term can tell apart prices
# at exactly zero, and a delta of zero is a figure every wrong reading of this path also produces.
DEADLINE = at(11, day=FRIDAY)
THE_PRICE = 4.375
THE_DEADLINE_MEASUREMENT = 0.4375
DEADLINE_RISK = "deadline_risk"

# The version the bump answers with, distinct from the version the assembler's own fake reports, so
# a response reporting the wrong one is visible.
BUMPED_TO = 4

WEIGHTS_READ = "weights.active"
DEADLINE_READ = "tasks.find"
FLOOR_READ = "areas.find"
PINS_HELD_READ = "pins.for_week"
ASSEMBLED = "assembler.assemble"
PRICED_THE_EDIT = "pin_price"
BUMPED = "versions.bump"
HELD = "pins.hold"
PROBED = "probe.verdict_for"
PRICED_THE_ROW = "pins.price"
RECORDED = "verdicts.record"
APPENDED = "edits.append"
SOLVE_REQUESTED = "coordinator.request_solve"

# `_held`'s sequence, as the module docstring's call-stack table states it. The feature snapshot is
# built inside the argument list of the append, so it is not a step of its own here; which frame it
# was handed is asserted separately.
THE_ORDER = (
    WEIGHTS_READ,
    DEADLINE_READ,
    FLOOR_READ,
    PINS_HELD_READ,
    ASSEMBLED,
    PRICED_THE_EDIT,
    BUMPED,
    HELD,
    ASSEMBLED,
    PROBED,
    PRICED_THE_ROW,
    RECORDED,
    APPENDED,
    SOLVE_REQUESTED,
)


class RecordingAssembler(WeekAssembler):
    """The real assembler, with every frame it answered kept in the order it answered them.

    Delegation rather than a subclass that calls ``super()``: what has to stay real is
    :meth:`WeekAssembler.assemble`, because the histogram observation lives inside it, and the
    eighteen collaborators belong to the assembler this wraps.
    """

    def __init__(self, real: WeekAssembler, log: list[str]) -> None:
        self._real = real
        self._log = log
        self.frames: list[SolveInputs] = []

    async def assemble(
        self,
        iso_week: IsoWeek,
        now: datetime,
        extra_adjustment: WeekAdjustment | None = None,
    ) -> SolveInputs:
        self._log.append(ASSEMBLED)
        frame = await self._real.assemble(iso_week, now, extra_adjustment)
        self.frames.append(frame)
        return frame


class RecordingProbe(WeekProbe):
    """The real probe under the request label, with the frame each call was handed."""

    def __init__(self, log: list[str]) -> None:
        super().__init__(caller=PROBE_CALLER)
        self._log = log
        self.frames: list[SolveInputs] = []

    def verdict_for(self, inputs: SolveInputs) -> Verdict:
        self._log.append(PROBED)
        self.frames.append(inputs)
        return super().verdict_for(inputs)


class RecordingWeights(WeightSetRepository):
    """The active weight set every figure this drive produces is priced under."""

    def __init__(self, log: list[str]) -> None:
        self._log = log
        self._active = a_weight_set()

    async def active(self) -> WeightSetRecord | None:
        self._log.append(WEIGHTS_READ)
        return self._active


class RecordingTasks(TaskRepository):
    """The task the pinned block holds, answered by id."""

    def __init__(self, stored: TaskRecord, log: list[str]) -> None:
        self._stored = stored
        self._log = log

    async def find(self, task_id: TaskId) -> TaskRecord | None:
        self._log.append(DEADLINE_READ)
        return self._stored if self._stored.id == task_id else None


class RecordingAreas(AreaRepository):
    """The Area the pinned block belongs to, answered by id."""

    def __init__(self, stored: AreaRecord, log: list[str]) -> None:
        self._stored = stored
        self._log = log

    async def find(self, area_id: AreaId) -> AreaRecord | None:
        self._log.append(FLOOR_READ)
        return self._stored if self._stored.id == area_id else None


class RecordingPins(PinRepository):
    """The two statements a pin is written with, over one held record."""

    def __init__(self, log: list[str]) -> None:
        self._log = log
        self.held: list[PinToHold] = []
        self.priced: list[float] = []
        self._record: PinRecord | None = None

    async def for_week(self, iso_week: IsoWeek) -> tuple[PinRecord, ...]:
        self._log.append(PINS_HELD_READ)
        return ()

    async def hold(self, pin: PinToHold) -> PinRecord:
        self._log.append(HELD)
        self.held.append(pin)
        self._record = PinRecord(
            id=uuid4(),
            tenant_id=TENANT,
            iso_week=pin.iso_week,
            block_id=pin.block_id,
            binding=pin.binding,
            interval=pin.interval,
            superseded_placement=pin.superseded_placement,
            objective_delta=None,
            weight_set_version=pin.weight_set_version,
            created_at=pin.created_at,
        )
        return self._record

    async def price(self, pin_id: PinId, *, objective_delta: float) -> PinRecord:
        self._log.append(PRICED_THE_ROW)
        self.priced.append(objective_delta)
        assert self._record is not None, "priced a pin this fake was never asked to hold"
        return PinRecord(
            id=self._record.id,
            tenant_id=self._record.tenant_id,
            iso_week=self._record.iso_week,
            block_id=self._record.block_id,
            binding=self._record.binding,
            interval=self._record.interval,
            superseded_placement=self._record.superseded_placement,
            objective_delta=objective_delta,
            weight_set_version=self._record.weight_set_version,
            created_at=self._record.created_at,
        )


class RecordingPlacements:
    """The placement seam, answering with whatever the pin store holds at the moment it is read.

    Production reads pins from the table ``pins.hold`` writes, so an assembly taken after the hold
    sees the row and one taken before it does not. Without that, both frames of one request would be
    equal values and the only thing separating them would be their identity.
    """

    def __init__(self, pins: RecordingPins, *, live_plan: PlanDocument) -> None:
        self._pins = pins
        self._live_plan = live_plan

    async def read(self, iso_week: IsoWeek, span: Interval) -> WeekPlacements:
        return WeekPlacements(
            live_plan=self._live_plan,
            pins=tuple(
                a_pin(binding=one.binding, interval=one.interval) for one in self._pins.held
            ),
        )


class RecordingEdits(EditEventRepository):
    """The edit event the pin is recorded with, kept rather than written."""

    def __init__(self, log: list[str]) -> None:
        self._log = log
        self.appended: list[EditToRecord] = []

    async def append(self, edit: EditToRecord) -> EditEventId:
        self._log.append(APPENDED)
        self.appended.append(edit)
        return uuid4()


class RecordingVerdicts(VerdictRecorder):
    """The transition recorder, answering that this verdict was not news.

    ``None`` is the ordinary answer and it is the one that keeps this module about the order of the
    writes: a row would need a verdict-event table, which is the integration tier's subject.
    """

    def __init__(self, log: list[str]) -> None:
        self._log = log

    async def record(
        self, iso_week: IsoWeek, verdict: Verdict, *, caused_by: OperationId | None = None
    ) -> VerdictEventRecord | None:
        self._log.append(RECORDED)
        return None


class RecordingVersions(WeekInputVersionRepository):
    """The week's version row: bumped by the service, read by the assembler it also serves."""

    def __init__(self, log: list[str]) -> None:
        self._log = log
        self.bumps: list[datetime] = []

    async def current(self, iso_week: IsoWeek) -> int | None:
        return BUMPED_TO - 1

    async def bump(self, iso_week: IsoWeek, *, at: datetime) -> int:
        self._log.append(BUMPED)
        self.bumps.append(at)
        return BUMPED_TO


class RecordingProposals(PendingProposalRepository):
    """No proposal awaits assent, so the pin's counterfactual is the plan of record."""

    def __init__(self) -> None:
        """Composed with no session: the one method a pin reaches answers without a statement."""

    async def find(self, iso_week: IsoWeek) -> None:
        return None


class RecordingRevisions(PlanRepository):
    """The plan of record, as the stored object a route reads it from."""

    def __init__(self, latest: PlanRevisionRecord) -> None:
        self._latest = latest

    async def latest(self, iso_week: IsoWeek) -> PlanRevisionRecord | None:
        return self._latest

    async def latest_approved(self, iso_week: IsoWeek) -> PlanRevisionRecord | None:
        return None


class RecordingCoordinator(SolveCoordinator):
    """The solve every pin asks for, recorded with the version it was asked at."""

    def __init__(self, log: list[str]) -> None:
        self._log = log
        self.requested: list[int] = []

    async def request_solve(
        self,
        week: IsoWeek,
        at_version: int,
        *,
        immediate: bool = False,
        candidate: JsonDocument | None = None,
    ) -> OperationRecord:
        self._log.append(SOLVE_REQUESTED)
        self.requested.append(at_version)
        return OperationRecord(
            id=uuid4(),
            tenant_id=TENANT,
            kind=SOLVE,
            status=PENDING,
            iso_week=week,
            source_id=None,
            input_version=at_version,
            candidate_adjustment=None,
            scheduled_for=NOW,
            started_at=None,
            finished_at=None,
            result_revision_id=None,
            superseded_by=None,
            attempt=1,
            error_code=None,
            error_message=None,
        )


class Driven:
    """One pin request, and everything it was observed doing.

    Held as one value because every claim below is about the same drive: the order, the frames, and
    the two histograms all have to be readings of one request or they are readings of nothing.
    """

    def __init__(
        self,
        *,
        log: Sequence[str],
        assembler: RecordingAssembler,
        probe: RecordingProbe,
        pins: RecordingPins,
        edits: RecordingEdits,
        priced_in: Sequence[SolveInputs],
        snapshotted_in: Sequence[SolveInputs],
    ) -> None:
        self.log = tuple(log)
        self.assembler = assembler
        self.probe = probe
        self.pins = pins
        self.edits = edits
        self.priced_in = tuple(priced_in)
        self.snapshotted_in = tuple(snapshotted_in)


async def drive_one_pin() -> Driven:
    """Pin one block through the public method a route calls, over real instruments.

    The two module-level functions the service calls are wrapped rather than replaced, so what they
    were handed is observable while what they compute is the shipped arithmetic: the price the row
    carries is the price :func:`pin_price` really returned for this frame.
    """
    log: list[str] = []
    area = an_area(area_id=uuid4())
    task = a_task(area_id=area.id, deadline=DEADLINE)
    block = a_task_block(task_id=task.id, area_id=area.id, interval=PROPOSED)
    plan = a_plan(blocks=(block,))
    versions = RecordingVersions(log)
    pins = RecordingPins(log)
    assembler = RecordingAssembler(
        an_assembler(
            areas=FakeAreas([area]),
            tasks=FakeTasks([task]),
            versions=versions,
            placements=RecordingPlacements(pins, live_plan=plan),
            caller=ASSEMBLY_CALLER,
        ),
        log,
    )
    probe = RecordingProbe(log)
    edits = RecordingEdits(log)
    service = PinService(
        assembler=assembler,
        probe=probe,
        revisions=RecordingRevisions(_a_revision(plan)),
        proposals=RecordingProposals(),
        pins=pins,
        edits=edits,
        verdicts=RecordingVerdicts(log),
        versions=versions,
        weights=RecordingWeights(log),
        coordinator=RecordingCoordinator(log),
        tasks=RecordingTasks(task, log),
        areas=RecordingAreas(area, log),
        clock=lambda: NOW,
    )
    priced_in: list[SolveInputs] = []
    snapshotted_in: list[SolveInputs] = []

    with (
        patch(
            f"{PinService.__module__}.pin_price",
            _watching(pin_price, log, PRICED_THE_EDIT, priced_in),
        ),
        patch(
            f"{PinService.__module__}.edit_context",
            _watching(edit_context, log, None, snapshotted_in),
        ),
    ):
        await service.pin(
            _a_principal(), str(WEEK), PinRequested(block_id=block.id, start=ACCEPTED.start)
        )

    return Driven(
        log=log,
        assembler=assembler,
        probe=probe,
        pins=pins,
        edits=edits,
        priced_in=priced_in,
        snapshotted_in=snapshotted_in,
    )


async def test_one_pin_request_holds_the_row_and_prices_it_at_the_figure_the_frame_produced() -> (
    None
):
    """The precondition every claim below rests on: the drive performs a pin, at a real price.

    Without it a wiring that refused the request early would leave every count at zero, every frame
    list empty, and each of the assertions below true of a request that did nothing. The price is
    asserted as an equality rather than as a sign, because the delta this fixture produces is the
    difference the deadline term measures and a re-sourced price is a different number rather than a
    missing one.
    """
    driven = await drive_one_pin()

    assert len(driven.pins.held) == 1, "no pin row was held, so this drive pinned nothing"
    assert driven.pins.held[0].interval == ACCEPTED
    assert driven.pins.held[0].superseded_placement == PROPOSED
    assert driven.pins.priced == [THE_PRICE]
    assert len(driven.edits.appended) == 1, "no edit event was recorded beside the pin"
    recorded = driven.edits.appended[0]
    assert recorded.objective_delta == THE_PRICE
    assert recorded.context.measurement_delta is not None
    assert recorded.context.measurement_delta[DEADLINE_RISK] == THE_DEADLINE_MEASUREMENT
    assert recorded.context.was_deadline_constrained is True


async def test_one_pin_request_takes_two_assembly_observations_and_one_probe_observation() -> None:
    """The reading an operator sizing the request path takes, measured rather than stated.

    The assembly histogram's p95 under this label is therefore the cost of ONE of a request's two
    assemblies. Counted as a delta across one request, because both families are process-global and
    every other case in this session observes them too.
    """
    assemblies_before = _observations(ASSEMBLY_DURATION.collect(), ASSEMBLY_CALLER.value)
    probes_before = _observations(PROBE_DURATION.collect(), PROBE_CALLER.value)

    driven = await drive_one_pin()

    assemblies = _observations(ASSEMBLY_DURATION.collect(), ASSEMBLY_CALLER.value)
    probes = _observations(PROBE_DURATION.collect(), PROBE_CALLER.value)
    assert assemblies - assemblies_before == ASSEMBLIES_PER_PIN
    assert probes - probes_before == PROBES_PER_PIN
    assert len(driven.assembler.frames) == int(ASSEMBLIES_PER_PIN)
    assert len(driven.probe.frames) == int(PROBES_PER_PIN)


def test_the_two_labels_these_counts_are_read_under_are_the_pair_the_pin_wiring_binds(
    source_root: Path,
) -> None:
    """The crossing that stops the count above measuring a label production does not use.

    Read out of ``pins/injection.py``'s own source, in the shape ``test_verdict_surfaces.py`` reads
    the surface a module binds: the label travels on the collaborator rather than on the call, so
    nothing a request answers carries it back for a test to read.
    """
    bound = _callers_bound_by(source_root / "pins" / "injection.py")

    assert bound == {
        f"{type(ASSEMBLY_CALLER).__name__}.{ASSEMBLY_CALLER.name}",
        f"{type(PROBE_CALLER).__name__}.{PROBE_CALLER.name}",
    }, "the pin dependency binds a caller label these counts are not read under"


def test_a_wiring_that_binds_another_label_is_seen_by_that_crossing(tmp_path: Path) -> None:
    """The control on the reading above, so an AST walk that matched nothing cannot pass it.

    The walk is keyed on a keyword argument's name and the attribute it is given. A walk that had
    stopped matching would answer with the empty set for any module, which is the one answer the
    assertion above would read as "no other label is bound".
    """
    module = tmp_path / "injection.py"
    module.write_text(
        "PinService(\n"
        "    assembler=build_week_assembler(caller=AssemblyCaller.WORKER),\n"
        "    probe=WeekProbe(caller=ProbeCaller.REQUEST),\n"
        ")\n",
        encoding="utf-8",
    )

    assert _callers_bound_by(module) == {"AssemblyCaller.WORKER", "ProbeCaller.REQUEST"}


async def test_the_price_and_the_feature_snapshot_read_the_frame_taken_before_the_pin_row() -> None:
    """Both consumers of the pre-pin frame, held against the assembly that produced it.

    The two frames of one request are different values here, because the second one reads the pin
    row back: that is asserted first, so the identity below is a claim about which frame each
    consumer was handed rather than a comparison of two objects that agree anyway. Re-sourcing
    either consumer to the second frame is what this bites.
    """
    driven = await drive_one_pin()

    pre_pin, post_pin = driven.assembler.frames
    assert pre_pin.pins == (), (
        "the first assembly already saw a pin, so it is not the pre-pin frame"
    )
    assert len(post_pin.pins) == 1, "the second assembly did not read the pin row back"
    assert len(driven.priced_in) == 1
    assert len(driven.snapshotted_in) == 1
    assert driven.priced_in[0] is pre_pin
    assert driven.snapshotted_in[0] is pre_pin


async def test_the_verdict_reads_the_frame_taken_after_the_pin_row() -> None:
    """The other half: the frame the pin has entered has exactly one consumer.

    Stated as identity against the second assembly and as a non-identity against the first, so a
    path that probed the pre-pin frame fails here rather than answering a verdict about a week
    without the pin in it.
    """
    driven = await drive_one_pin()

    assert driven.probe.frames[0] is driven.assembler.frames[1]
    assert driven.probe.frames[0] is not driven.assembler.frames[0]


async def test_the_pin_row_is_held_between_the_two_assemblies_and_priced_after_the_second() -> None:
    """The whole sequence, as the call-stack table in ``pins/service.py`` states it.

    An equality over the ordered log rather than a set of pairwise orderings: a step that moves, a
    step that disappears and a step that runs twice are all one failing comparison, and the failure
    prints the sequence the service actually performed.
    """
    driven = await drive_one_pin()

    assert driven.log == THE_ORDER


def _observations(collected: object, caller: str) -> float:
    """How many observations this caller's histogram holds, from the samples a scraper reads."""
    return next(
        (
            sample.value
            for metric in collected  # type: ignore[attr-defined]
            for sample in metric.samples
            if sample.name.endswith("_count") and sample.labels.get(CALLER_LABEL) == caller
        ),
        0.0,
    )


def _callers_bound_by(module: Path) -> set[str]:
    """Every ``caller=`` a call in this module binds, as the spelling the source uses."""
    tree = ast.parse(module.read_text(encoding="utf-8"))
    return {
        f"{keyword.value.value.id}.{keyword.value.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == CALLER_LABEL
        and isinstance(keyword.value, ast.Attribute)
        and isinstance(keyword.value.value, ast.Name)
    }


def _watching(
    real: Callable[..., Any],
    log: list[str],
    step: str | None,
    frames: list[SolveInputs],
) -> Callable[..., Any]:
    """``real``, with the assembly it was handed kept and the shipped answer returned unchanged."""

    def watched(*args: Any, **kwargs: Any) -> Any:
        if step is not None:
            log.append(step)
        frames.append(kwargs["inputs"])
        return real(*args, **kwargs)

    return watched


def _a_revision(plan: PlanDocument) -> PlanRevisionRecord:
    """The plan of record this week holds, stored the way a revision row holds it."""
    return PlanRevisionRecord(
        id=uuid4(),
        tenant_id=TENANT,
        iso_week=WEEK,
        status="applied",
        reason="auto_applied_fill",
        document=stored_document(plan),
        objective_breakdown={},
        weight_set_version=1,
        input_version=BUMPED_TO - 1,
        supersedes_id=None,
        created_at=at(0),
        approved_at=None,
    )


def _a_principal() -> Principal:
    return Principal(tenant_id=TENANT, user_id=uuid4(), scopes=ALL_SCOPES)
