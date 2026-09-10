"""The paths, the resource name, and the vocabulary the concession routes read.

Two collections under one week, and they are deliberately two. ``tradeoffs`` is where a concession
is REQUESTED, which persists nothing and returns an operation; ``adjustments`` is where the
concessions a week already holds are read and revoked. One collection would have made a request and
an approved concession the same resource, and they are not: the request is a question about a week
and the approved concession is a decision about it.
"""

from __future__ import annotations

from typing import Final

from syncr_api.core.settings import API_PREFIX

# `/api/v1/weeks`, built from the versioned prefix rather than written out.
WEEKS_PREFIX: Final = f"{API_PREFIX}/weeks"

# Relative to the router's own prefix. The week is a path segment named as every other path
# parameter this api declares one: snake_cased, matching `{period_id}` and `{area_id}`. The route
# table writes `{isoWeek}`, which is the same URL with a different parameter NAME; the
# generated client reads the name, so one spelling across the api's routes is worth more than
# literal fidelity to an illustrative table.
TRADEOFFS_PATH: Final = "/{iso_week}/tradeoffs"
ADJUSTMENTS_PATH: Final = "/{iso_week}/adjustments"
ADJUSTMENT_PATH: Final = "/{iso_week}/adjustments/{adjustment_id}"

# The wire spelling of the week, which a field error names when the identifier will not parse. The
# path parameter's own name, so the error points at what the caller sent.
ISO_WEEK_FIELD: Final = "iso_week"
ISO_WEEK_EXAMPLE: Final = "2026-W07"

CONCESSION_RESOURCE: Final = "concession"
