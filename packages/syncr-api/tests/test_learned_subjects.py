"""What a parameter token's key resolves to, read at the level the parsing happens.

The route suite proves that the resolved word reaches a client. This proves the grammar the key is
written in, which a request cannot reach every corner of: a pair key, a key naming an Area the
reader does not hold, and a key that is not an identifier at all.

The names are handed in rather than read from a database, because the resolution is arithmetic over
one mapping: the read that composes that mapping is the service's, and it is proven where the
service is.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from syncr_api.learned.subjects import subject_of

FITNESS = uuid4()
CAREER = uuid4()
AREA_NAMES = {FITNESS: "Fitness", CAREER: "Career"}


class TestAKeyedParameterAnswersTheAreaItNames:
    def test_a_duration_multiplier_answers_the_name_of_the_area_in_its_key(self) -> None:
        assert subject_of(f"duration_multiplier[{FITNESS}]", AREA_NAMES) == "Fitness"

    def test_a_second_area_answers_its_own_name_rather_than_the_first_s(self) -> None:
        # One mapping, two Areas: a resolution that answered the first entry for every key would
        # pass every assertion above and fail this one.
        assert subject_of(f"time_of_day_fitness[{CAREER}]", AREA_NAMES) == "Career"

    def test_a_pair_key_answers_the_area_the_leading_half_names(self) -> None:
        # A skip probability is fitted per Area AND per part of the day, so its key is a pair. What
        # the row is about is still the Area.
        assert subject_of(f"skip_probability[{FITNESS},morning]", AREA_NAMES) == "Fitness"


class TestAParameterThatNamesNoAreaAnswersNothing:
    def test_a_parameter_with_no_key_answers_none(self) -> None:
        assert subject_of("objective_weights", AREA_NAMES) is None

    def test_a_key_naming_an_area_the_reader_does_not_hold_answers_none(self) -> None:
        # The raw key would be a UUID on a screen where every other row carries a name, and it would
        # be the identifier of something this reader cannot see.
        assert subject_of(f"duration_multiplier[{uuid4()}]", AREA_NAMES) is None

    def test_a_key_that_is_not_an_identifier_answers_none(self) -> None:
        assert subject_of("duration_multiplier[Fitness]", AREA_NAMES) is None

    def test_an_empty_key_answers_none(self) -> None:
        assert subject_of("duration_multiplier[]", AREA_NAMES) is None

    def test_a_parameter_read_against_no_areas_at_all_answers_none(self) -> None:
        assert subject_of(f"duration_multiplier[{FITNESS}]", {}) is None


class TestTheKeyIsTakenFromTheEndOfTheToken:
    def test_a_name_that_merely_contains_an_identifier_is_not_a_key(self) -> None:
        # The token is a parameter followed by a bracketed key, and a parameter with no brackets has
        # no key however much of one its name resembles.
        assert subject_of(f"duration_multiplier {FITNESS}", AREA_NAMES) is None

    def test_a_key_the_uuid_of_which_is_upper_case_answers_the_same_area(self) -> None:
        # Postgres and the fitter both spell an identifier in lower case, and a UUID compares by
        # value rather than by spelling, so a document written by hand still resolves.
        upper = str(FITNESS).upper()
        assert UUID(upper) == FITNESS
        assert subject_of(f"duration_multiplier[{upper}]", AREA_NAMES) == "Fitness"
