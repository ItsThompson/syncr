"""Pure syncr domain: entities, invariants, and arithmetic. No clock, and no I/O.

Every module here takes literals and returns literals, so the arithmetic the budget
report and the solver rest on is testable without a fixture stack. The purity is
asserted by this package's boundary suite rather than trusted: no module imports a
database library, a web framework, or a downstream package, none reads the time, and
none mints a value its inputs did not supply.

There is exactly one sanctioned read. ``zones`` resolves the IANA database through
``zoneinfo``, which reads it from disk, because a daylight-saving rule asserted against a
mocked offset asserts only what this package already believes. The read is cached, and
`tzdata` is a declared dependency so it behaves the same wherever the package runs.

One rule reaches beyond the package. **The interval algebra in ``intervals`` is never
mocked, in any layer.** A faked ``IntervalSet`` in a service test lets the service pass
while the arithmetic underneath it is wrong, which is the failure this product cannot
detect any other way.
"""
