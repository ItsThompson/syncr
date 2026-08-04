"""The table names, the route paths, and the two name bounds the day-shape routes read.

Every other bound this package enforces lives in ``syncr_domain.templates``, beside the shape
it constrains: a duration, a flex band, and the grid are properties of an entry rather than of
this module, and the week assembler reads them too. What is here is what only the HTTP layer
and the schema need.

The route paths spell the entry collection twice, once with an entry identifier and once
without, because ``POST`` addresses the collection and ``PATCH`` and ``DELETE`` address a
member. Both are relative to the templates prefix, so the version prefix is stated once.
"""

from __future__ import annotations

from typing import Final

from syncr_api.core.settings import API_PREFIX

DAY_TYPES_TABLE: Final = "day_types"
TEMPLATES_TABLE: Final = "templates"
TEMPLATE_ENTRIES_TABLE: Final = "template_entries"
WEEK_PATTERNS_TABLE: Final = "week_patterns"

# Built from the versioned prefix rather than written out, so a change to the prefix reaches
# this module.
DAY_TYPES_PREFIX: Final = f"{API_PREFIX}/day-types"
TEMPLATES_PREFIX: Final = f"{API_PREFIX}/templates"
WEEK_PATTERN_PREFIX: Final = f"{API_PREFIX}/week-pattern"

# Relative to the templates router's prefix.
TEMPLATE_PATH: Final = "/{template_id}"
TEMPLATE_ENTRIES_PATH: Final = "/{template_id}/entries"
TEMPLATE_ENTRY_PATH: Final = "/{template_id}/entries/{entry_id}"

DAY_TYPE_RESOURCE: Final = "day type"
TEMPLATE_RESOURCE: Final = "template"
TEMPLATE_ENTRY_RESOURCE: Final = "template entry"
WEEK_PATTERN_RESOURCE: Final = "week pattern"

# A day type's name is read in the week pattern's seven rows and in a template's own row, both
# of which are tight. The same bound an Area name carries, for the same reason.
DAY_TYPE_NAME_MAX_LENGTH: Final = 60
TEMPLATE_NAME_MAX_LENGTH: Final = 60
