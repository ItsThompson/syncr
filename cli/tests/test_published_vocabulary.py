"""The CLI's exit-code table, bound to the vocabulary the api publishes.

The api publishes its problem types as the enum on ``Problem.type`` in the committed contract,
``frontend/openapi.json``. The CLI's private map gives each one an exit code by convention alone:
the CLI ships nothing server-side and cannot import the hierarchy, so nothing else holds the two
together. This module does. Crossing in both directions is what bounds the map's lifetime to the
catalog's: a type the api deletes stops living in the map forever, and a type the api adds cannot
reach a client with no row.
"""

from __future__ import annotations

import json
from pathlib import Path

from syncr_cli.problems import EXIT_CODE_BY_PROBLEM_TYPE

# The committed contract, resolved from this file's own depth in the tree, as
# `test_cli_reference` resolves the reference it pins.
CONTRACT_PATH = Path(__file__).resolve().parents[2] / "frontend" / "openapi.json"

# The namespace the CLI mints its own problem types under, shared with the api's so a caller
# matching on a prefix sees where a problem came from. Rows are told apart by this prefix rather
# than by a list of names, so a seventh cli- type needs no edit here.
CLI_PREFIX = "syncr:cli-"


def published_types() -> frozenset[str]:
    """The vocabulary the committed contract publishes for ``Problem.type``.

    Read off the property's own subschema rather than searched for in the document's text: every
    type is named in some description somewhere, so a text search answers true for a document that
    publishes no enum at all.
    """
    document = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    field = document["components"]["schemas"]["Problem"]["properties"]["type"]
    published = field.get("enum", ())
    assert published, "the committed contract publishes no problem types"
    return frozenset(published)


def test_the_exit_code_table_and_the_published_catalog_agree_in_both_directions() -> None:
    # The published types must all have rows: a type the api adds would otherwise reach a client
    # whose only rule for it is the status fallback. And every row that claims the api's namespace
    # must still be published: a type the api deletes would otherwise live in the map forever,
    # answering a condition nothing sends.
    #
    # Neither exclusion names a type. The CLI's own rows are excluded by the prefix above;
    # ``syncr:http-error`` demands no row because it is absent from the published hierarchy itself
    # -- no class declares it -- and it is caught here if a row ever appears, because no published
    # type carries it either.
    rows = frozenset(EXIT_CODE_BY_PROBLEM_TYPE)
    published = published_types()

    unmapped = sorted(published - rows)
    assert not unmapped, (
        f"the api publishes {unmapped} and the CLI's exit-code table has no row; add one to "
        "`EXIT_CODE_BY_PROBLEM_TYPE` or drop the type from the api"
    )
    orphaned = sorted(one for one in rows - published if not one.startswith(CLI_PREFIX))
    assert not orphaned, (
        f"the CLI's exit-code table maps {orphaned}, which the api does not publish; remove the "
        "row the api deleted"
    )
