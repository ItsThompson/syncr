"""``python -m syncr_cli``, which is the console script by another name.

Present so the package can be driven without an installed entry point, which is what a test
harness and a container both want.

The guard is load-bearing rather than ceremonial: this module is a module, so anything that walks
the package -- the import-boundary probe, a documentation tool -- imports it, and without the
guard that import would run the CLI.
"""

from __future__ import annotations

from syncr_cli.main import main

if __name__ == "__main__":
    main()
