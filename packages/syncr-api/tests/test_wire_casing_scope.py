"""Which casing each wire surface uses, read off the committed contract.

``core/schemas.py`` fixes camelCase for a request or response body. The clause this file holds is
the other half of that rule: a path parameter is snake_cased, and a multi-word query parameter the
api names itself is camelCased. A rule stated for bodies and read as covering paths is what makes
the next route declare ``{isoWeek}``, and only the artifact a client generates from can settle
which spelling shipped.

**Three census units, because a census's unit is its blind spot.**

``parameters_in_the_templates`` reads one PATH STRING and answers with the placeholders in it.
``parameters_the_operations_declare`` reads one PARAMETER OBJECT and answers with its name and its
location. A case spanning both -- a placeholder no operation declares, or a declared path parameter
no template carries -- is invisible to each of them separately, which is what the agreement
crossing exists for.

``properties_of`` reads one NAMED SCHEMA under ``components.schemas``. A body shape declared inline
under ``paths`` spans that unit rather than sitting inside it, so a separate assertion holds that
none is. A red there means the property census has stopped covering the body surface, not that a
casing broke.

**Nothing here derives its expectation from its subject.** The camel hump and the snake_case shape
are literal patterns, and where a spelling is allowed to appear is read from the clause in the
source rather than from the parameter the clause describes.

Every claim is taken over two documents: the committed artifact a client was generated from, and
the one the application declares today. A committed file can be older than the routes it
describes, and the regenerate-and-diff CI job is the only gate that sees them disagree.

The two body surfaces are told apart by the media type that reaches them rather than by name: the
OAuth endpoints take ``application/x-www-form-urlencoded`` requests whose member names RFC 6749,
RFC 7009 and RFC 7636 fix, and no JSON body reaches those schemas. The exception is therefore
structural, and it is asserted to be non-empty, because an exception that describes nothing is a
sentence in the docstring that has stopped being true.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import pytest

from syncr_api.core import schemas as casing_rule
from tests.test_alert_rules import repo_root

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping

    from fastapi import FastAPI

# The document the committed client was generated from, which is what a caller reads. The
# application's own document is the other reading, because a committed file can describe an older
# set of routes than the one HEAD mounts and no local gate can see that.
CONTRACT: Final = repo_root() / "frontend" / "openapi.json"

JSON_BODY: Final = "application/json"
FORM_BODY: Final = "application/x-www-form-urlencoded"

# The hump the whole question turns on: a lowercase run followed immediately by an uppercase
# letter, which is what tells `isoWeek` from `iso_week`. Searched rather than matched, so a hump
# anywhere in a name answers.
CAMEL_HUMP: Final = re.compile(r"[a-z]+[A-Z]")

# The shape a path parameter is spelled in.
SNAKE_CASED: Final = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*")

# The shape a body member is spelled in, and a query parameter this api names itself.
CAMEL_CASED: Final = re.compile(r"[a-z][a-zA-Z0-9]*")

# The shape a header parameter is spelled in: capitalized words joined by hyphens, which is what a
# generated client spells even though a header name is case-insensitive on the wire.
HEADER_CASED: Final = re.compile(r"[A-Z][A-Za-z0-9]*(?:-[A-Z][A-Za-z0-9]*)*")

# A placeholder in a path template.
PLACEHOLDER: Final = re.compile(r"\{([^{}]*)\}")

# A spelling quoted in a docstring, which is how a clause's own examples are read back.
QUOTED: Final = re.compile(r"``([^`]+)``")

PATH: Final = "path"
QUERY: Final = "query"
HEADER: Final = "header"

# Every method an OpenAPI path item may carry an operation under. Named rather than inferred from
# the keys present, so a path-item-level `parameters` list is read as the shared declaration it is
# instead of being mistaken for an operation.
HTTP_METHODS: Final = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)

# Floors, measured against the committed contract, not an authoritative list. Every casing claim
# below is a universal, and a universal over an empty set holds: these are what make the claims
# non-vacuous. A red here means the wire surface SHRANK, which is a deliberate change and a figure
# to re-measure rather than a casing that broke.
PATHS_AT_LEAST: Final = 81
PATH_PARAMETER_NAMES_AT_LEAST: Final = 21
BODY_MEMBERS_AT_LEAST: Final = 781


def is_camel_humped(name: str) -> bool:
    """Whether ``name`` carries a lowercase-to-uppercase hump, as ``isoWeek`` does."""
    return CAMEL_HUMP.search(name) is not None


def is_snake_cased(name: str) -> bool:
    """Whether ``name`` is one or more lowercase words joined by underscores."""
    return SNAKE_CASED.fullmatch(name) is not None


def is_camel_cased(name: str) -> bool:
    """Whether ``name`` is a lowercase-initial run of letters and digits, humps allowed."""
    return CAMEL_CASED.fullmatch(name) is not None


def is_header_cased(name: str) -> bool:
    """Whether ``name`` is capitalized words joined by hyphens, as a header is written."""
    return HEADER_CASED.fullmatch(name) is not None


@dataclass(frozen=True, slots=True, kw_only=True)
class Parameter:
    """One parameter the contract declares, and the reading it was found by."""

    name: str
    location: str
    where: str

    def __str__(self) -> str:
        return f"{self.where} [{self.location}] {self.name}"


def contract() -> Mapping[str, Any]:
    """The committed document, parsed."""
    document: Mapping[str, Any] = json.loads(CONTRACT.read_text(encoding="utf-8"))
    return document


def paths(document: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    holder: Mapping[str, Mapping[str, Any]] = document["paths"]
    return holder


def named_schemas(document: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    holder: Mapping[str, Mapping[str, Any]] = document.get("components", {}).get("schemas", {})
    return holder


def operations(document: Mapping[str, Any]) -> Iterator[tuple[str, str, Mapping[str, Any]]]:
    """Every operation in the document, as its path, its method, and its own body."""
    for path, item in paths(document).items():
        for method, operation in item.items():
            if method in HTTP_METHODS:
                yield path, method, operation


def parameters_in_the_templates(document: Mapping[str, Any]) -> tuple[Parameter, ...]:
    """Every placeholder of every path template, read from the path string.

    The name a client's generated call has to spell is the placeholder's, so this reading is the
    one a URL carries. It cannot see a declaration, which is what the second reading is for.
    """
    return tuple(
        Parameter(name=name, location=PATH, where=path)
        for path in paths(document)
        for name in PLACEHOLDER.findall(path)
    )


def parameters_the_operations_declare(document: Mapping[str, Any]) -> tuple[Parameter, ...]:
    """Every parameter object of every operation, including a path item's shared ones.

    A parameter declared by reference carries no name and is reported separately rather than
    skipped quietly: this reading would otherwise go blind on a document that used one.
    """
    found: list[Parameter] = []
    for path, item in paths(document).items():
        shared = item.get("parameters", ())
        for method, operation in item.items():
            if method not in HTTP_METHODS:
                continue
            for declared in (*shared, *operation.get("parameters", ())):
                if "name" not in declared:
                    continue
                found.append(
                    Parameter(
                        name=declared["name"],
                        location=declared["in"],
                        where=f"{method.upper()} {path}",
                    )
                )
    return tuple(found)


def parameters_declared_by_reference(document: Mapping[str, Any]) -> tuple[str, ...]:
    """Every parameter object that points elsewhere instead of naming a parameter."""
    return tuple(
        f"{method.upper()} {path} -> {declared['$ref']}"
        for path, method, operation in operations(document)
        for declared in (
            *paths(document)[path].get("parameters", ()),
            *operation.get("parameters", ()),
        )
        if "name" not in declared and "$ref" in declared
    )


def references_in(node: object) -> frozenset[str]:
    """Every named schema ``node`` reaches, at any depth and through any keyword."""
    found: set[str] = set()
    if isinstance(node, dict):
        reference = node.get("$ref")
        if isinstance(reference, str):
            found.add(reference.rsplit("/", 1)[-1])
        for value in node.values():
            found |= references_in(value)
    elif isinstance(node, list):
        for value in node:
            found |= references_in(value)
    return frozenset(found)


def schemas_reached_through(document: Mapping[str, Any], media: str) -> frozenset[str]:
    """Every named schema a body of ``media`` reaches, following each one into its own.

    The media type is what tells the two body surfaces apart. Reading them by name would need a
    list of the OAuth schemas, and a list is right on the day it is written.
    """
    seeds: set[str] = set()
    for _path, _method, operation in operations(document):
        holders = [operation.get("requestBody", {}).get("content", {})]
        holders.extend(
            response.get("content", {}) for response in operation.get("responses", {}).values()
        )
        for holder in holders:
            if media in holder:
                seeds |= references_in(holder[media].get("schema", {}))
    return _closure(document, seeds)


def _closure(document: Mapping[str, Any], seeds: set[str]) -> frozenset[str]:
    schemas = named_schemas(document)
    reached: set[str] = set()
    pending = list(seeds)
    while pending:
        name = pending.pop()
        if name in reached or name not in schemas:
            continue
        reached.add(name)
        pending.extend(references_in(schemas[name]))
    return frozenset(reached)


def properties_of(document: Mapping[str, Any], names: frozenset[str]) -> tuple[str, ...]:
    """Every member of every named schema in ``names``, as ``Schema.member``."""
    schemas = named_schemas(document)
    return tuple(
        f"{name}.{member}"
        for name in sorted(names)
        for member in schemas[name].get("properties", {})
    )


def body_shapes_declared_inline(document: Mapping[str, Any]) -> tuple[str, ...]:
    """Every member-bearing schema written under ``paths`` instead of being named."""
    return tuple(sorted(_inline(paths(document), trail=("paths",))))


def _inline(node: object, *, trail: tuple[str, ...]) -> Iterator[str]:
    if isinstance(node, dict):
        if isinstance(node.get("properties"), dict):
            yield "/".join(trail)
        for key, value in node.items():
            yield from _inline(value, trail=(*trail, str(key)))
    elif isinstance(node, list):
        for position, value in enumerate(node):
            yield from _inline(value, trail=(*trail, str(position)))


def spellings_the_clause_quotes() -> tuple[str, ...]:
    """Every spelling quoted in the casing docstring, in the order it names them."""
    stated = casing_rule.__doc__
    assert stated is not None, "the casing docstring is not present in the imported module"
    return tuple(QUOTED.findall(stated))


READINGS: Final[Mapping[str, Callable[[Mapping[str, Any]], tuple[Parameter, ...]]]] = {
    "templates": parameters_in_the_templates,
    "declarations": parameters_the_operations_declare,
}


@pytest.fixture(params=["committed", "served"])
def document(request: pytest.FixtureRequest, app: FastAPI) -> Mapping[str, Any]:
    """Both documents, because a committed file can be older than the routes it describes.

    The committed one is what the client was generated from, so it is what a caller reads. The
    served one is what the application declares today, so a route added without a regeneration is
    held to the casing claim before the artifact catches up. Only the regenerate-and-diff CI job
    makes the two agree, and a stale committed file is invisible to every local contract gate.
    """
    if request.param == "committed":
        return contract()
    served: Mapping[str, Any] = app.openapi()
    return served


def test_each_reading_of_the_contract_finds_something(document: Mapping[str, Any]) -> None:
    # Every claim below is a universal over one of these readings, so all of them hold vacuously
    # on a document that declares nothing. The floors are measured against the committed
    # contract, and the two schema sets are asserted to partition the named schemas so that a
    # shape reached by neither cannot sit uncensused.
    declared = parameters_the_operations_declare(document)
    by_reference = parameters_declared_by_reference(document)
    from_json = schemas_reached_through(document, JSON_BODY)
    from_form = schemas_reached_through(document, FORM_BODY)
    members = properties_of(document, from_json)

    assert len(paths(document)) >= PATHS_AT_LEAST, (
        f"the contract declares {len(paths(document))} paths, fewer than the "
        f"{PATHS_AT_LEAST} measured when this floor was written"
    )
    path_parameters = {one.name for one in declared if one.location == PATH}
    assert len(path_parameters) >= PATH_PARAMETER_NAMES_AT_LEAST, (
        f"{len(path_parameters)} distinct path parameters, fewer than the "
        f"{PATH_PARAMETER_NAMES_AT_LEAST} measured when this floor was written"
    )
    assert parameters_in_the_templates(document), "no path template carries a placeholder"
    assert {one.location for one in declared} >= {PATH, QUERY, HEADER}, (
        "a parameter surface the clause states a spelling for was not read at all, so that "
        f"spelling's claim holds over nothing: read {sorted({one.location for one in declared})}"
    )
    assert by_reference == (), (
        "a parameter is declared by reference, which the declaration reading cannot follow: "
        f"{by_reference}"
    )
    assert len(members) >= BODY_MEMBERS_AT_LEAST, (
        f"{len(members)} members reached through a JSON body, fewer than the "
        f"{BODY_MEMBERS_AT_LEAST} measured when this floor was written"
    )
    assert from_form, (
        "no form-encoded body reaches a named schema, so the exception the casing docstring "
        "states for the OAuth requests describes nothing"
    )
    assert not from_json & from_form, (
        f"a schema is reached by both body surfaces, so neither claim bounds it: "
        f"{sorted(from_json & from_form)}"
    )
    assert set(named_schemas(document)) == from_json | from_form, (
        "a named schema is reached by neither body surface, so no casing claim covers it: "
        f"{sorted(set(named_schemas(document)) - (from_json | from_form))}"
    )


@pytest.mark.parametrize("read", READINGS.values(), ids=READINGS.keys())
def test_no_path_declares_a_camel_humped_parameter(
    document: Mapping[str, Any],
    read: Callable[[Mapping[str, Any]], tuple[Parameter, ...]],
) -> None:
    humped = [
        str(one) for one in read(document) if one.location == PATH and is_camel_humped(one.name)
    ]

    assert humped == [], f"a path parameter is camelCased: {humped}"


@pytest.mark.parametrize("read", READINGS.values(), ids=READINGS.keys())
def test_every_path_parameter_is_snake_cased(
    document: Mapping[str, Any],
    read: Callable[[Mapping[str, Any]], tuple[Parameter, ...]],
) -> None:
    # The stronger half of the same claim: a name with no hump is not necessarily snake_case, and
    # `ISOWeek` would satisfy the hump reading while spelling the surface two ways.
    otherwise = [
        str(one) for one in read(document) if one.location == PATH and not is_snake_cased(one.name)
    ]

    assert otherwise == [], (
        f"a path parameter is spelled neither snake_case nor a bare word: {otherwise}"
    )


def test_the_two_readings_of_the_path_parameters_agree(document: Mapping[str, Any]) -> None:
    """The case that spans both units: a placeholder and a declaration that disagree.

    A URL carries the placeholder and a generated client spells the declared name, so a document
    where the two differ has a parameter that cannot be called by the name it publishes. Neither
    reading alone can see it.
    """
    in_templates = {one.name for one in parameters_in_the_templates(document)}
    in_declarations = {
        one.name for one in parameters_the_operations_declare(document) if one.location == PATH
    }

    assert in_templates == in_declarations, (
        f"placeholder with no declaration: {sorted(in_templates - in_declarations)}. Declared "
        f"path parameter no template carries: {sorted(in_declarations - in_templates)}"
    )


def test_every_camel_humped_parameter_is_a_query_parameter(document: Mapping[str, Any]) -> None:
    """Where camelCase does live on the parameter surface, which is the clause's other half.

    Stated as the whole set rather than as the two names, so snake_casing one of them reddens
    here as well: a docstring saying the query surface is camelCased needs a query parameter that
    is, and an empty set would satisfy the path claim while making the clause false.
    """
    humped = [
        one for one in parameters_the_operations_declare(document) if is_camel_humped(one.name)
    ]

    assert humped, "no parameter is camelCased anywhere, so the clause names a surface that is not"
    elsewhere = [str(one) for one in humped if one.location != QUERY]
    assert elsewhere == [], f"a camelCased parameter is not a query parameter: {elsewhere}"


def test_every_body_member_a_json_route_carries_is_camel_cased(
    document: Mapping[str, Any],
) -> None:
    reached = schemas_reached_through(document, JSON_BODY)

    otherwise = [
        member
        for member in properties_of(document, reached)
        if not is_camel_cased(member.split(".", 1)[1])
    ]

    assert otherwise == [], f"a JSON body member is not camelCased: {otherwise}"


def test_the_form_bodies_are_where_a_snake_cased_member_lives(
    document: Mapping[str, Any],
) -> None:
    """The exclusion's other edge, which is what stops the body claim from being a rule with a
    hole nobody stated: the members RFC 6749, RFC 7009 and RFC 7636 fix are snake_cased, and they
    are reached only through a form-encoded request.
    """
    fixed = properties_of(document, schemas_reached_through(document, FORM_BODY))

    assert fixed, "the form-encoded bodies declare no member at all"
    assert [member for member in fixed if "_" in member.split(".", 1)[1]], (
        f"no form-encoded member is snake_cased, so the exception is describing nothing: {fixed}"
    )


def test_no_form_member_carries_a_camel_hump(document: Mapping[str, Any]) -> None:
    """The bound on the members this api adds to a form body rather than reads from an RFC.

    The RFCs fix all but one of those names, so the exclusion above says nothing about the one
    this api owns and nothing about the next one. This is what the casing docstring's "none of
    them is camelCased" rests on, and it is the arm a multi-word api-owned member reddens.
    """
    members = properties_of(document, schemas_reached_through(document, FORM_BODY))

    humped = [member for member in members if is_camel_humped(member.split(".", 1)[1])]
    assert humped == [], f"a form-encoded member is camelCased: {humped}"


def test_every_header_parameter_is_spelled_as_a_header(document: Mapping[str, Any]) -> None:
    """The third parameter surface, which is the second one the casing rule does not reach.

    One name holds this surface today, so the claim is thin, and the location floor in
    ``test_each_reading_of_the_contract_finds_something`` is what keeps it from becoming a claim
    about nothing.
    """
    otherwise = [
        str(one)
        for one in parameters_the_operations_declare(document)
        if one.location == HEADER and not is_header_cased(one.name)
    ]

    assert otherwise == [], f"a header parameter is spelled as neither a header is: {otherwise}"


def test_no_body_shape_is_declared_inline_under_a_path(document: Mapping[str, Any]) -> None:
    """The member census's own blind spot, held shut rather than described.

    It reads a named schema. A shape written inline under an operation carries members that no
    named schema holds, so it would be covered by no casing claim at all.
    """
    inline = body_shapes_declared_inline(document)

    assert inline == (), f"a member-bearing schema is declared inline rather than named: {inline}"


def test_the_casing_clause_names_spellings_the_contract_declares(
    document: Mapping[str, Any],
) -> None:
    """The clause crossed against the artifact it describes.

    The docstring's examples are read out of it and looked up in the contract, so a clause quoting
    a spelling the contract does not declare on the surface it assigns it reddens. Deleting the
    clause empties every arm below.

    **The misplacement check runs on a camel-humped spelling only, and the asymmetry is not an
    oversight.** Nothing on this wire camelCases a path parameter and no RFC camelCases anything,
    so "camelCased implies query" cannot refuse a true sentence. The mirror rule would: five query
    parameters are snake_cased because RFC 6749 and RFC 7636 fix their names, so a clause that
    explained those by name would be refused for stating a fact.
    """
    declared = {one.name: one.location for one in parameters_the_operations_declare(document)}
    quoted = [one for one in spellings_the_clause_quotes() if one in declared]

    misplaced = {
        one: declared[one] for one in quoted if is_camel_humped(one) and declared[one] != QUERY
    }
    assert misplaced == {}, (
        f"the casing docstring quotes a camelCased spelling the contract declares outside the "
        f"query surface: {misplaced}"
    )
    assert [one for one in quoted if declared[one] == PATH], (
        "the casing docstring quotes no path parameter the contract declares, so the clause "
        "scoping the rule away from the path surface is not there to be read"
    )
    assert [one for one in quoted if declared[one] == QUERY], (
        "the casing docstring quotes no query parameter the contract declares, so the half of "
        "the clause that says where camelCase does belong is not there to be read"
    )
    assert "path parameter" in (casing_rule.__doc__ or ""), (
        "the casing docstring does not name a path parameter at all"
    )


def test_the_readings_answer_from_the_shape_rather_than_from_the_document() -> None:
    # The readers' and the predicates' own control, which no mutation of the contract can supply:
    # a reading that answered nothing would leave every universal above green, and one that
    # answered too much would name a body member as a parameter. Each input is a case the
    # readings have to tell apart.
    invented: Mapping[str, Any] = {
        "paths": {
            "/things/{thingId}": {
                "parameters": [{"name": "shared_id", "in": PATH}],
                "get": {
                    "parameters": [
                        {"name": "thingId", "in": PATH},
                        {"name": "sinceWhen", "in": QUERY},
                        {"name": "Trace-Id", "in": HEADER},
                    ],
                    "responses": {
                        "200": {"content": {JSON_BODY: {"schema": {"$ref": "#/x/Thing"}}}}
                    },
                },
                "summary": "not an operation",
            },
            "/forms": {
                "post": {
                    "requestBody": {"content": {FORM_BODY: {"schema": {"$ref": "#/x/Form"}}}},
                    "responses": {"204": {}},
                },
            },
        },
        "components": {
            "schemas": {
                "Thing": {"properties": {"thingId": {}, "nested": {"$ref": "#/x/Deep"}}},
                "Deep": {"properties": {"seen_at": {}}},
                "Form": {"properties": {"grant_type": {}}},
            }
        },
    }

    assert [str(one) for one in parameters_in_the_templates(invented)] == [
        "/things/{thingId} [path] thingId"
    ]
    assert [str(one) for one in parameters_the_operations_declare(invented)] == [
        "GET /things/{thingId} [path] shared_id",
        "GET /things/{thingId} [path] thingId",
        "GET /things/{thingId} [query] sinceWhen",
        "GET /things/{thingId} [header] Trace-Id",
    ], "a path item's shared parameters belong to each of its operations, and `summary` is not one"
    assert schemas_reached_through(invented, JSON_BODY) == frozenset({"Thing", "Deep"}), (
        "a JSON body reaches the shapes its own members name"
    )
    assert schemas_reached_through(invented, FORM_BODY) == frozenset({"Form"})
    assert properties_of(invented, frozenset({"Thing", "Deep"})) == (
        "Deep.seen_at",
        "Thing.thingId",
        "Thing.nested",
    ), "named schemas in a stable order, each one's members in the order it declares them"
    assert body_shapes_declared_inline(invented) == ()

    assert is_camel_humped("isoWeek")
    assert not is_camel_humped("iso_week")
    assert not is_camel_humped("Idempotency-Key"), "an uppercase after a hyphen is not a hump"
    assert is_snake_cased("anchor_type_id")
    assert not is_snake_cased("isoWeek")
    assert not is_snake_cased("Idempotency-Key")
    assert is_camel_cased("atRisk")
    assert not is_camel_cased("grant_type")
    assert not is_camel_cased("Problem")
    assert is_header_cased("Idempotency-Key")
    assert not is_header_cased("idempotency_key")
    assert not is_header_cased("Idempotency-key"), "each word of a header name is capitalized"


def test_the_inline_reading_sees_a_shape_written_under_an_operation() -> None:
    # The positive control for the assertion that finds none in the contract: an absence is only
    # evidence when the reading that found it can find one.
    invented: Mapping[str, Any] = {
        "paths": {
            "/things": {
                "post": {
                    "requestBody": {
                        "content": {JSON_BODY: {"schema": {"properties": {"thing_id": {}}}}}
                    },
                    "responses": {"204": {}},
                }
            }
        },
        "components": {"schemas": {}},
    }

    assert body_shapes_declared_inline(invented) == (
        "paths//things/post/requestBody/content/application/json/schema",
    )
