"""What a learned parameter is about, resolved from the key its own token carries.

A maturity row names its parameter as ``name`` or as ``name[key]``, and the key is the identifier of
the Area the fit is about, followed for a skip probability by the part of the day it was measured
in. So the Area is in the token and nowhere else on the row: twelve duration multipliers arrive as
twelve rows whose every other word is identical, and a client cannot read a name out of a UUID.

Resolved here, against the Areas this tenant holds, because that is where the rest of the row's
words are composed and because the names are one read the whole payload shares.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_domain.identifiers import AreaId

# The key a parameter token carries, if it carries one. Brackets cannot nest: the fitter composes
# the token from one parameter and one key, and the key is an identifier plus a bucket name.
_KEYED = re.compile(r"\[(?P<key>[^\[\]]*)\]$")

# What a pair key joins. A skip probability is fitted per Area AND per part of the day, and the Area
# is the leading half.
_PAIR_SEPARATOR = ","


def subject_of(parameter: str, area_names: Mapping[AreaId, str]) -> str | None:
    """The name of the Area ``parameter`` is about, or nothing because it names no Area.

    ``None`` where the parameter has no key at all, which is the state of every parameter fitted
    once for the whole account. It is also the answer for a key naming an Area this tenant does not
    hold: a stored row outlives nothing in P0, where Areas are permanent, so that is a document
    written against another account or a malformed one, and answering with the raw key would put a
    UUID on a screen instead of a name.
    """
    keyed = _KEYED.search(parameter)
    if keyed is None:
        return None
    area_id = _an_area_id(keyed.group("key").split(_PAIR_SEPARATOR, 1)[0])
    return None if area_id is None else area_names.get(area_id)


def _an_area_id(key: str) -> AreaId | None:
    try:
        return UUID(key)
    except ValueError:
        return None
