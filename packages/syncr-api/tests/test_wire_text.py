"""User text on the wire is stripped before its bound and refused when it is not text.

Three claims, each stated once here and checked against every field the walk finds:

* surrounding whitespace is stripped BEFORE the length bound is applied, so a name of only
  spaces is refused as the nothing it is rather than stored as padding
* a control character, NUL included, is refused as a caller error instead of reaching the
  driver and answering 500 at flush
* every field whose value is a length-bounded string reaches that reading through the ONE
  shared type, so a new field cannot be laxer than the rest by being spelled differently

The population comes from ``tests/wire_census.py``, which discovers it: a string with a
length bound anywhere in its annotation, whether or not it has adopted the shared spelling.
``null`` is outside the claim: on a nullable name it still means "no name", and the walk
finds those fields only to assert that ``None`` still passes through.

A password is deliberately exempt. It is bounded, but it is not a name: it is taken as
typed, never stripped, and a control character in it is no one's error but the caller's own
secret. The same holds for the Google payload identifiers and the OAuth access token, none
of which the walk reaches because none of them extends the wire base or rides on a route.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, get_args

import pytest
from pydantic import ValidationError

import syncr_api
from syncr_api.core.app_factory import create_app
from syncr_api.core.settings import EnvSettings, build_service_settings
from tests.wire_census import (
    TextField,
    models_the_contract_is_generated_from,
    names_the_shared_text,
    text_fields,
    wire_models,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

# What pydantic calls each refusal, so a test asserts the reason rather than only the failure.
TOO_SHORT: Final = "too_short"
CONTROL_CHARACTER: Final = "value_error"

# The shapes this walk must reach. Named so that narrowing the walk is a red suite rather than a
# quieter one: one title per intention module, one nullable name per shape family, the list whose
# ITEMS are names, an identifier the week view authors, and a zone key.
LANDMARKS: Final = frozenset(
    {
        "syncr_api.tasks.schemas.TaskCreateRequest.title",
        "syncr_api.routines.schemas.RoutinePatchRequest.title",
        "syncr_api.habits.schemas.HabitCreateRequest.variants",
        "syncr_api.areas.schemas.AreaCreateRequest.name",
        "syncr_api.areas.schemas.ProjectPatchRequest.name",
        "syncr_api.templates.schemas.TemplateCreateRequest.name",
        "syncr_api.offplan.schemas.OffPlanCreateRequest.label",
        "syncr_api.offplan.schemas.OffPlanPatchRequest.label",
        "syncr_api.anchors.schemas.AnchorTypeCreateRequest.name",
        "syncr_api.calendars.schemas.AddCalendarSourceRequest.external_id",
        "syncr_api.pins.schemas.PinCreateRequest.block_id",
        "syncr_api.user_settings.schemas.TravelOverrideRequest.zone",
        "syncr_api.accounts.schemas.LoginRequest.email",
    }
)

# The one bounded string the claim does not reach: not user-authored text, so never stripped.
EXEMPT: Final = frozenset({"syncr_api.accounts.schemas.LoginRequest.password"})

# An application built at COLLECTION time, because each field is its own case and pytest needs the
# population before a fixture has run. Built the way the suite's own fixture builds one, from
# defaults alone, so a developer's environment cannot change what is collected.
_COLLECTED = create_app(
    build_service_settings(service="syncr-api-census", env=EnvSettings(_env_file=None))
)
TEXT_FIELDS: Final = text_fields(wire_models(_COLLECTED))
DOCUMENT_FIELDS: Final = text_fields(models_the_contract_is_generated_from(_COLLECTED))

# A value carrying NUL past a length check: long enough to clear any min bound, wrong in the one
# way this surface exists to refuse.
NUL_TEXT: Final = "Italy\x00"


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """One case per field, named after the field it is about.

    The skip count runs high by design: exempt and not-applicable fields skip here rather
    than being filtered out of the population, so every exemption stays visible per field
    and each one is compensated by an exact-set or positive-control assertion elsewhere.
    """
    if "field" in metafunc.fixturenames:
        metafunc.parametrize("field", TEXT_FIELDS, ids=[one.where for one in TEXT_FIELDS])


def where(fields: tuple[TextField, ...]) -> set[str]:
    return {field.where for field in fields}


def _refusals_of(error: ValidationError) -> set[str]:
    return {one["type"] for one in error.errors()}


def _is_nullable(field: TextField) -> bool:
    return any(argument is type(None) for argument in get_args(field.annotation))


class TestTheWalkReachesTheWholeSurface:
    """The census's own reach, before anything is asserted through it."""

    def test_it_measures_the_checkout_whose_behaviour_this_file_asserts(self) -> None:
        # The control for every figure here: the walk and the behaviour asserted must be answers
        # about the same checkout.
        root = Path(__file__).resolve().parents[3]
        imported = Path(syncr_api.__file__ or "").resolve()

        assert imported.is_relative_to(root), (
            f"{imported} is imported from outside {root}, so the walk and the behaviour asserted "
            "here are answers about two different checkouts"
        )

    def test_it_reaches_every_shape_named_here(self, app: FastAPI) -> None:
        assert where(text_fields(wire_models(app))) >= LANDMARKS

    def test_it_reaches_more_than_the_shapes_named_here(self, app: FastAPI) -> None:
        # A walk trimmed to its own landmarks would satisfy the test above and assert nothing
        # about the surface, which is the failure this file exists to avoid.
        assert where(text_fields(wire_models(app))) - LANDMARKS

    def test_it_finds_nothing_the_document_walk_does_not(self, app: FastAPI) -> None:
        # Both walks descend from one predicate, so this is a crossing rather than a bound: the
        # document's own population must account for everything the base walk reached.
        assert where(text_fields(wire_models(app))) <= where(DOCUMENT_FIELDS)


class TestEveryTextFieldIsSpelledOnce:
    def test_the_field_reaches_its_reading_through_the_shared_type(self, field: TextField) -> None:
        if field.where in EXEMPT:
            pytest.skip("not user-authored text; its exemption is asserted as a set below")

        assert names_the_shared_text(field.annotation), (
            f"{field.where} declares a bounded string of its own. The one in core/schemas.py is "
            "the reading every user-authored text field takes."
        )

    def test_the_only_bounded_string_off_the_shared_type_is_exempt(self) -> None:
        unadopted = {one.where for one in TEXT_FIELDS if not names_the_shared_text(one.annotation)}
        assert unadopted == EXEMPT


class TestWhitespaceIsStrippedBeforeTheBound:
    @pytest.mark.parametrize("blank", ["", "   "], ids=["empty", "whitespace_only"])
    def test_a_value_that_is_nothing_after_stripping_is_refused_as_too_short(
        self, field: TextField, blank: str
    ) -> None:
        if field.where in EXEMPT:
            pytest.skip("not user-authored text")
        # The bite is in the reason: raw, both values clear a min_length of 1, so a refusal
        # typed too_short says the strip ran first.
        with pytest.raises(ValidationError) as refusal:
            field.accept(blank)

        assert TOO_SHORT in _refusals_of(refusal.value), field.where

    def test_padding_does_not_count_against_the_bound(self, field: TextField) -> None:
        if field.where in EXEMPT:
            pytest.skip("not user-authored text")
        _, high = field.bounds
        if high is None:
            pytest.skip("the field declares no upper bound to pad against")
        padded = f" {'a' * high} "

        accepted = field.accept(padded)

        stripped = ["a" * high] if field.repeated else "a" * high
        assert accepted == stripped, field.where


class TestAControlCharacterIsRefusedRatherThanStored:
    def test_a_nul_byte_is_a_stated_refusal(self, field: TextField) -> None:
        if field.where in EXEMPT:
            pytest.skip("not user-authored text")
        with pytest.raises(ValidationError) as refusal:
            field.accept(NUL_TEXT)

        assert CONTROL_CHARACTER in _refusals_of(refusal.value), field.where

    def test_a_control_character_is_refused_before_anything_is_returned(
        self, field: TextField
    ) -> None:
        if field.where in EXEMPT:
            pytest.skip("not user-authored text")
        # A value whose control byte sits inside an otherwise acceptable name: the refusal must
        # be the shared one, not a silent trim that kept the rest.
        carried = f"Italy\x00{'a' * 4}"

        with pytest.raises(ValidationError) as refusal:
            field.accept(carried)

        assert CONTROL_CHARACTER in _refusals_of(refusal.value), field.where


class TestNullOnANullableNameStillMeansNoName:
    def test_a_nullable_field_accepts_null(self, field: TextField) -> None:
        if not _is_nullable(field):
            pytest.skip("the field is not nullable")

        assert field.adapter.validate_python(None) is None

    def test_the_walk_finds_at_least_one_nullable_name(self) -> None:
        # A positive control for the test above, which otherwise passes forever once the walk
        # stops finding nullable fields at all.
        nullable = {one.where for one in TEXT_FIELDS if _is_nullable(one)}

        assert nullable


class TestTheDocumentNamesTheSharedTextInOnePlace:
    def test_the_shared_type_is_declared_once_and_as_plain_text(self, app: FastAPI) -> None:
        # Strip and the control-character refusal are validation, not wire shape: the component
        # the alias renders is the bare string, so generated clients read no new member.
        schemas = app.openapi().get("components", {}).get("schemas", {})

        assert schemas.get("WireText") == {"type": "string"}

    def test_every_bounded_string_the_document_declares_references_it(self, app: FastAPI) -> None:
        # THE UPPER BOUND over the wire itself rather than over the models: the document is what
        # a caller reads, so a bounded string rendered WITHOUT the shared reference is a field
        # the surface adopted in the models but not on the wire. The password is the one
        # deliberate exception, and it is named rather than counted.
        declaring = _bounded_string_paths(app.openapi())

        assert declaring, "the walk found no bounded strings in the document at all"
        unreferenced = {
            path for path in declaring if not _references_shared_text(app.openapi(), path)
        }
        assert unreferenced <= _EXEMPT_DOCUMENT_PATHS, (
            f"these bounded strings reach the wire without the shared type: {sorted(unreferenced)}"
        )


# Bounded strings the document may carry without the shared reference, each with its reason:
# a credential is taken as typed, and a promotion id is an opaque path identifier the client
# echoes back, not text a user authors.
_EXEMPT_DOCUMENT_PATHS: Final = frozenset(
    {
        ("components", "schemas", "LoginRequest", "properties", "password"),
        ("paths", "/api/v1/promotions/{promotion_id}/accept", "post", "parameters", "0", "schema"),
        ("paths", "/api/v1/promotions/{promotion_id}/decline", "post", "parameters", "0", "schema"),
    }
)


def _bounded_string_paths(document: Any, path: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    """Every schema node that states a string length bound, by its path."""
    found: set[tuple[str, ...]] = set()
    if isinstance(document, dict):
        bounded = (document.get("type") == "string" or "$ref" in document) and (
            document.get("minLength") is not None or document.get("maxLength") is not None
        )
        if bounded:
            found.add(path)
        for key, value in document.items():
            found |= _bounded_string_paths(value, (*path, str(key)))
    elif isinstance(document, list):
        for index, value in enumerate(document):
            found |= _bounded_string_paths(value, (*path, str(index)))
    return found


def _references_shared_text(document: Any, path: tuple[str, ...]) -> bool:
    """Whether the schema node at ``path`` names the shared component beside its bound."""
    if not isinstance(document, dict):
        return False
    node: dict[str, Any] | list[Any] = document
    for part in path:
        if isinstance(node, list):
            node = node[int(part)]
        else:
            child = node.get(part)
            if not isinstance(child, (dict, list)):
                return False
            node = child
    return isinstance(node, dict) and node.get("$ref") == "#/components/schemas/WireText"
