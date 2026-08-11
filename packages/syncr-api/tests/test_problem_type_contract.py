"""The vocabulary ``Problem.type`` publishes, crossed against the hierarchy that declares it.

``type`` used to be an unbounded string, so a generated client could not type the one member of
a problem document a caller branches on. It now carries an enum, and the enum is the api's own
error hierarchy: :func:`~syncr_api.core.errors.declared_problem_types` walks
:class:`~syncr_api.core.errors.SyncrError`, and the schema hook calls it while the document is
being generated. A seventeenth subclass therefore reaches the contract by existing.

**Three readings, and no two of them are derived from each other.** The walk answers from the
classes the process has imported. The source reading answers from the package's own files as
text, so it reaches a subclass in a module nothing imports, which is the one defect the walk
cannot see: the document is generated from an application, so a type in an unreachable module is
silently absent from it. The document answers from the published artifact, in two versions -- the
one the runtime serves and the one committed for the client generator -- so a type deleted from
the code and left in the committed file reddens.

The crossings are equalities in both directions. Publishing a type nothing declares is as wrong
as declaring one the document omits: the first types a value no caller can receive.

**One type a caller receives is deliberately absent**, and the last test here is what keeps that
honest rather than forgotten: ``syncr:http-error`` is rendered directly by the handler for a
status no subclass claims, so no class declares it and no walk of the hierarchy can reach it. That
test drives it onto the wire in the same breath as it asserts the vocabulary omits it, because an
assertion of absence alone would also pass for a wire that never carries it at all.

What this file cannot do: it reads the document, not the generated client. Whether the enum
survives into ``frontend/src/api/schema.d.ts`` is `just contract` and the frontend's own
``lint:contract`` check, and whether the CLI's exit-code table has heard of a type is that
package's business, since it ships nothing server-side and cannot import this hierarchy.
"""

from __future__ import annotations

import ast
import json
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import pytest

from syncr_api.core.errors import GENERIC_HTTP_ERROR_TYPE, declared_problem_types
from tests.source_census import api_sources
from tests.test_alert_rules import repo_root

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

# The committed contract, resolved through the installed package rather than through this file's
# own depth in the tree.
CONTRACT = repo_root() / "frontend" / "openapi.json"

# The class attribute a subclass fixes its wire type with.
TYPE_ATTRIBUTE = "type"

# A GET-only route of the real application, so a wrong method reaches the handler for a status no
# subclass claims. Any route would do; this one needs no session and no database.
GET_ONLY_PATH = "/readyz"


def bound_type(statement: ast.stmt) -> str | None:
    """The string a class-body statement binds to ``type``, and nothing for any other statement.

    A bare assignment of a literal, which is how a subclass fixes its wire type. An annotated
    field is deliberately not one: ``Problem`` itself declares ``type: str = Field(...)``, and a
    reading that counted it would publish the name of a pydantic call as a problem type.
    """
    if not isinstance(statement, ast.Assign):
        return None
    bound = any(
        isinstance(target, ast.Name) and target.id == TYPE_ATTRIBUTE for target in statement.targets
    )
    if not bound:
        return None
    value = statement.value
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return None


def types_assigned_in(source: str) -> set[str]:
    """Every string a class body in ``source`` binds to ``type``."""
    return {
        found
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ClassDef)
        for statement in node.body
        if (found := bound_type(statement)) is not None
    }


def types_declared_by_source() -> Mapping[Path, set[str]]:
    """Every type the package's own sources declare, by the file that declares it.

    Over the whole package rather than the three modules that hold the hierarchy today, so a
    subclass written in a fourth module is read here with no edit.
    """
    declaring = {
        path: types_assigned_in(path.read_text(encoding="utf-8")) for path in api_sources()
    }
    return {path: found for path, found in declaring.items() if found}


def types_declared_in_the_sources() -> set[str]:
    return set().union(*types_declared_by_source().values())


def published_types(document: Mapping[str, Any]) -> set[str]:
    """The vocabulary a document publishes for ``Problem.type``.

    Read off the property's own subschema, never searched for in the document's text: every type
    is named in some description somewhere, so a text search answers true for a document that
    publishes no enum at all.
    """
    field: Mapping[str, Any] = document["components"]["schemas"]["Problem"]["properties"]["type"]
    assert field["type"] == "string", f"the field is no longer a string: {field}"
    published: set[str] = set(field.get("enum", ()))
    return published


def served_document(client: TestClient) -> Mapping[str, Any]:
    """The document the runtime serves, which is what a client generated today would read."""
    answered = client.get("/openapi.json")
    assert answered.status_code == HTTPStatus.OK, answered.text
    document: Mapping[str, Any] = answered.json()
    return document


def committed_document(_client: TestClient) -> Mapping[str, Any]:
    """The document in the tree, which is what the committed client WAS generated from."""
    document: Mapping[str, Any] = json.loads(CONTRACT.read_text(encoding="utf-8"))
    return document


DOCUMENTS: Mapping[str, Callable[[TestClient], Mapping[str, Any]]] = {
    "served": served_document,
    "committed": committed_document,
}


def test_each_reading_of_the_vocabulary_finds_something(client: TestClient) -> None:
    # Every crossing below is an equality between derived sets, so all of them hold vacuously if
    # a reading goes blind. The last assertion is the one with teeth: the source reading is what
    # catches a subclass in a module nothing imports, and it can only catch one while the types
    # are spread across more than one module, because a reading of a single file would otherwise
    # agree with the walk by luck.
    declaring = types_declared_by_source()

    assert declared_problem_types(), "the hierarchy walk reached no type at all"
    assert types_declared_in_the_sources(), "the source reading found no declared type"
    for name, read_document in DOCUMENTS.items():
        assert published_types(read_document(client)), f"the {name} document publishes no type"
    assert len(declaring) > 1, (
        f"only {sorted(path.name for path in declaring)} declares a type, so the source reading "
        "would agree with the walk even if it read one file"
    )


@pytest.mark.parametrize("read_document", DOCUMENTS.values(), ids=DOCUMENTS.keys())
def test_the_published_vocabulary_is_exactly_what_the_hierarchy_declares(
    client: TestClient,
    read_document: Callable[[TestClient], Mapping[str, Any]],
) -> None:
    walked = set(declared_problem_types())
    published = published_types(read_document(client))

    assert published == walked, (
        f"{len(walked)} type(s) are declared and {len(published)} published. Declared and "
        f"unpublished: {sorted(walked - published)}. Published and declared by no class: "
        f"{sorted(published - walked)}. Regenerate with `just contract` and commit "
        "frontend/openapi.json with frontend/src/api/schema.d.ts."
    )


def test_every_type_the_sources_declare_is_one_the_hierarchy_walk_reaches(app: FastAPI) -> None:
    # The application is built rather than merely imported, so the crossing does not depend on what
    # `conftest.py` happens to import. The walk reaches a subclass only in a module something
    # imported, and both published documents are generated from a built application, so this is the
    # state the crossing has to be taken in.
    assert app.routes, (
        "no router is mounted, so the walk is taken over an application that is not one"
    )

    walked = set(declared_problem_types())
    read = types_declared_in_the_sources()

    assert walked == read, (
        "declared in a source no module imports, so no document can carry it: "
        f"{sorted(read - walked)}. Walked but declared in none of this package's sources, so "
        "either the class is declared outside this package or its `type` is not the plain string "
        f"literal this reading requires: {sorted(walked - read)}."
    )


def test_the_generic_type_reaches_the_wire_and_the_vocabulary_does_not_carry_it(
    client: TestClient,
) -> None:
    """The one type a caller receives that the published vocabulary omits.

    Omitted by the shape of the walk rather than by a rule that names it: nothing raises it, so
    no class declares it. The wire half of this test is what stops the omission from being read
    as a type that never appears.
    """
    refused = client.delete(GET_ONLY_PATH)

    assert refused.status_code == HTTPStatus.METHOD_NOT_ALLOWED, refused.text
    assert refused.json()["type"] == GENERIC_HTTP_ERROR_TYPE
    assert GENERIC_HTTP_ERROR_TYPE not in declared_problem_types()
    assert GENERIC_HTTP_ERROR_TYPE not in published_types(served_document(client))


def test_the_source_reading_answers_from_a_class_body_binding_alone() -> None:
    # The reader's own control, and the one no mutation of this file can supply: a reader that
    # answered nothing at all would leave every crossing above green only if the walk also went
    # blind, and a reader that answered too much would publish a string from an unrelated class.
    # Each input below is a defect this file has to tell apart from a declaration.
    annotated = "class Problem:\n    type: str = Field(json_schema_extra=publish)\n"
    module_level = "type = 'syncr:not-a-class-attribute'\n"
    computed = "class Computed(Conflict):\n    type = PREFIX + 'conflict'\n"
    another_name = "class Other(Conflict):\n    kind = 'syncr:kind'\n"
    declared = "class RequestInFlight(Conflict):\n    type = 'syncr:request-in-flight'\n"
    nested = "class Outer:\n    class Inner(Conflict):\n        type = 'syncr:inner'\n"

    assert types_assigned_in(annotated) == set(), "an annotated field is not a bound type"
    assert types_assigned_in(module_level) == set(), "a module-level name is not a class's"
    assert types_assigned_in(computed) == set(), "an expression is not a published literal"
    assert types_assigned_in(another_name) == set(), "another attribute is not this one"
    assert types_assigned_in(declared) == {"syncr:request-in-flight"}
    assert types_assigned_in(nested) == {"syncr:inner"}
