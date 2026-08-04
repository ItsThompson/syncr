"""The outcome-state vocabulary, stated in two packages, asserted to be one set.

``syncr_domain.outcomes.OutcomeState`` is what the rotation cursor and the debt derivation are
stated over. ``syncr_api.plans.config.OUTCOME_STATES`` is what the ``block_outcomes`` check
constraint enforces. Both describe the same five states, and neither can import the other: the
domain package must not import the api, and a migration must not import the workspace at all.

So the two statements are checked against each other here, in the one package that can see both.
Without this, a sixth state added to either side would leave a row the database accepts and the
derivations classify as neither a completion nor a miss, or a state the derivations expect and no
row can hold.
"""

from __future__ import annotations

from syncr_api.plans.config import MOVED_OUTCOME, OUTCOME_STATES, PARTIAL_OUTCOME
from syncr_domain.outcomes import COMPLETION_STATES, MISS_STATE, OutcomeState


def test_the_stored_vocabulary_and_the_domain_vocabulary_are_the_same_set() -> None:
    assert {state.value for state in OutcomeState} == set(OUTCOME_STATES)


def test_the_two_states_plan_storage_names_individually_are_domain_states() -> None:
    """Both carry a check constraint of their own, so both have to name a state that exists."""
    assert OutcomeState(PARTIAL_OUTCOME) is OutcomeState.PARTIAL
    assert OutcomeState(MOVED_OUTCOME) is OutcomeState.MOVED


def test_every_stored_state_is_classified_as_a_completion_or_as_a_miss() -> None:
    """A state the database can hold and the derivations ignore would be counted nowhere."""
    classified = {state.value for state in COMPLETION_STATES} | {MISS_STATE.value}

    assert classified == set(OUTCOME_STATES)
