"""Solve orchestration: the ``Operation`` resource and, later, the coordinator.

This package holds the operation table, its vocabulary, and the repository over it. The
coordinator, the claim, the debounce, and the worker loop arrive with the ticket that builds
the worker, and they build on the schema here.
"""
