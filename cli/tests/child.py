"""The environment a child process of this suite runs in.

Three tests in this member start a process, and every one of them has to point the child at the tree
the parent imported: a subprocess inherits none of the parent's ``sys.path``, so without being told
it resolves this package through the interpreter's editable install and measures a different
checkout. That has already been the failure mode twice here, so the environment has one owner.

One module rather than one helper per file, because two files deriving the same thing independently
is how the two came to handle ``PATH`` differently, and the third launch site somebody adds is where
the hole comes back.
"""

from __future__ import annotations

import os
from pathlib import Path

import syncr_cli

# Where this suite's own interpreter imported the package from. Every child is pointed here.
SOURCE_ROOT = Path(syncr_cli.__file__).resolve().parent.parent


def child_environment(**stated: str) -> dict[str, str]:
    """The environment a child runs in: this tree on its path, plus whatever a caller states.

    ``PATH`` is carried through because a child may need to find an interpreter or a subprocess of
    its own; nothing else of the ambient environment is, so a variable on the developer's machine
    cannot change what a test measures.
    """
    return {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(SOURCE_ROOT),
        **stated,
    }
