"""Conflict-resolution errors that describe the block the request cannot move."""

from __future__ import annotations

from syncr_api.core.errors import Conflict


class BlockAlreadyStarted(Conflict):
    """409: a resolution cannot move a block whose start the week has reached."""

    type = "syncr:block-already-started"
    title = "Block already started"
