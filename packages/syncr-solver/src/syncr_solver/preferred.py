"""What the user's preferences say about a placement, and what a fitted number adds to it.

Two objective terms read a preference and they read different halves of one. The misfit term
asks whether a block sits inside the windows its content prefers; the fragmentation term asks how
long the ideal session for that content is. Both need the same resolution first -- whose
preference applies to this block -- so it is stated once, here.

## The resolution is two lookups, not a chain walk

The producer already resolved every override, so what arrives is one preference per owner rather
than two to merge: a habit that declares none carries its Area's, under its own owner. The
content's own therefore comes first and its Area's is the fallback, because an override REPLACES
its Area's declaration wholly.

An owner that declares an EMPTY window list is a statement rather than an omission: it opts out
of a preference the rest of its Area keeps. So no window means no charge, which falls out of
measuring against the windows that exist rather than against a count of them.

## The four components, and why they are components rather than terms

A declared ``strong`` window, a declared ``soft`` window, the fitted fitness of the hour, and the
fitted probability the user refuses that part of the day. One weight scales all four, so the
scales below are constants of the term rather than numbers anyone fits: four weights would
quadruple what the learner must fit from the sparsest signal the product has, which is the same
argument that keeps ``staleness`` one term.

Strong is an ORDER OF MAGNITUDE above soft, which is the ratio the design fixes. Neither can
refuse a placement: H5 was withdrawn because a hard rule with a conditional escape is not a hard
rule, and a preference for a morning gym is a claim about quality rather than a statement of
impossibility. So the worst a block suffers here is the full component.

**Only one of the two declared components can apply to any block.** One preference exists per
owner and it carries one strength, and an override replaces its Area's declaration wholly, so a
block has strong windows or soft ones and never both. See :data:`MISFIT_MAX`.

The two fitted components sit at the soft scale. A declared window is the user's own statement and
a fitted number is an inference from their behaviour, so an inference does not outrank a
declaration.

**An absent fitted parameter contributes nothing, and that is not the same as one fitted at
zero.** A parameter below its maturity gate is not applied at all rather than at a reduced weight,
and absence is how the weight set expresses that. Read as a default, an absent fitness would
enter as ``1 - 0`` and become the largest fitted charge the term can carry, which is the inverse
of the rule.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from syncr_domain.preferences import PreferenceStrength
from syncr_solver.weights import bucket_of

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from syncr_domain.identifiers import AreaId
    from syncr_domain.identity import BindingRef
    from syncr_domain.intervals import Interval
    from syncr_solver.inputs import ResolvedPreference
    from syncr_solver.weights import WeightSet

MISFIT_STRONG: Final = 1.0
MISFIT_SOFT: Final = 0.1
MISFIT_FITTED_FITNESS: Final = 0.1
MISFIT_FITTED_SKIP: Final = 0.1

MISFIT_MAX: Final = MISFIT_STRONG + MISFIT_FITTED_FITNESS + MISFIT_FITTED_SKIP
"""The most the components can charge one block. What the misfit term divides by.

**The two declared components cannot both fire, so the maximum is not their sum.** A preference
carries one strength, one preference exists per owner (three unique indexes in the api enforce
it), and an override replaces its Area's declaration wholly. So exactly one declared preference
applies to any block, and the most it can charge is the strong component. The design's own
formula adds a strong term to a soft term, and that sum has two mutually exclusive addends: it is
a selection written as a sum, and the correction is filed as ticket 1344.

The arithmetic below still charges both where both are present, rather than picking one. A
producer that emitted two strengths for one owner would then read above 1.0 rather than silently
normalizing to a maximum it had passed, which is the same direction ``budget_deviation`` errs in
for an over-allocated Area.
"""

# Each declared strength paired with what violating it costs, in the order the components are
# stated. Data rather than two branches, so the ratio between them is one expression a test reads.
DECLARED_COMPONENTS: Final[tuple[tuple[PreferenceStrength, float], ...]] = (
    (PreferenceStrength.STRONG, MISFIT_STRONG),
    (PreferenceStrength.SOFT, MISFIT_SOFT),
)


class ResolvedPreferences:
    """The week's preferences, indexed by the owner each was resolved under.

    An index rather than a scan per block, and keyed on the owner's identifier rather than on the
    owner value: a habit's own preference and its Area's arrive under different kinds of owner, and
    a block asks for either by the identifier it holds.
    """

    __slots__ = ("_by_owner",)

    def __init__(self, preferences: Sequence[ResolvedPreference]) -> None:
        indexed: dict[object, list[ResolvedPreference]] = {}
        for preference in preferences:
            indexed.setdefault(preference.owner.id, []).append(preference)
        self._by_owner = {owner: tuple(found) for owner, found in indexed.items()}

    def applying_to(self, binding: BindingRef, area_id: AreaId) -> tuple[ResolvedPreference, ...]:
        """This content's own preferences, or its Area's where it declares none."""
        own = self._by_owner.get(binding.entity_id)
        if own:
            return own
        return self._by_owner.get(area_id, ())

    def windows_of(
        self, binding: BindingRef, area_id: AreaId, strength: PreferenceStrength
    ) -> tuple[Interval, ...]:
        """Every window of one strength that applies to this content, resolved for this week."""
        return tuple(
            window
            for preference in self.applying_to(binding, area_id)
            if preference.strength is strength
            for window in preference.windows
        )

    def ideal_session_minutes(self, binding: BindingRef, area_id: AreaId) -> int | None:
        """The ideal length of one session of this content, or nothing because none is declared.

        The largest where several preferences name one. **That ``max`` cannot fire today**, because
        one preference exists per owner, so the list never holds two: substituting ``min`` reddens
        nothing. It is kept rather than reduced to a single read for two reasons. It costs nothing,
        and it is the safe direction if the per-owner index ever relaxes: taking the largest is the
        only reading under which declaring a second preference cannot make a plan look better.

        That is a different case from a GUARD that cannot fire, which this ticket deleted one of. A
        guard that cannot fire raises on nothing and states a rule the code does not need; this is
        an ordinary expression whose input happens to be short today.
        """
        stated = [
            preference.preferred_duration_minutes
            for preference in self.applying_to(binding, area_id)
            if preference.preferred_duration_minutes is not None
        ]
        return max(stated) if stated else None


def misfit_of(
    placement: Interval,
    *,
    binding: BindingRef,
    area_id: AreaId,
    hour: int,
    preferences: ResolvedPreferences,
    weights: WeightSet,
) -> float:
    """What one placement costs against when its work should happen, over the four components.

    ``hour`` is the local hour the placement starts in, resolved by the caller, because the zone a
    date was declared in is a fact about the week rather than about a preference.
    """
    cost = sum(
        component
        for strength, component in DECLARED_COMPONENTS
        if _is_outside_every(placement, preferences.windows_of(binding, area_id, strength))
    )
    fitness = weights.fitness_at(area_id, hour)
    if fitness is not None:
        cost += MISFIT_FITTED_FITNESS * (1.0 - fitness)
    skip = weights.skip_at(area_id, bucket_of(hour))
    if skip is not None:
        cost += MISFIT_FITTED_SKIP * skip
    return cost


def _is_outside_every(placement: Interval, windows: Iterable[Interval]) -> bool:
    """Whether no window holds the whole of this placement, and there was a window to hold it.

    Containment rather than overlap, because a session running past the window it was preferred in
    happened partly outside it, and a preference is about when the work happens rather than about
    when it starts.

    An owner with no windows is outside nothing. That is what makes an empty declaration an opt-out
    rather than a placement that violates every window there is.
    """
    stated = tuple(windows)
    if not stated:
        return False
    return not any(
        window.start <= placement.start and placement.end <= window.end for window in stated
    )
