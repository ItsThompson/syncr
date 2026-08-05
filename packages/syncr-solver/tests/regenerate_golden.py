"""Regenerate the reference week's golden file after a deliberate change.

``python -m tests.regenerate_golden`` from the member's directory. It writes what the current code
produces, so the diff it leaves in the working tree is the change under review: run it, read the
diff, and keep it only if every line of it was intended.
"""

from __future__ import annotations

from tests.test_reference_week import GOLDEN, rendered, solved_reference


def main() -> None:
    GOLDEN.write_text(rendered(solved_reference()), encoding="utf-8")
    print(f"wrote {GOLDEN}")


if __name__ == "__main__":
    main()
