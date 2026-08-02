"""Pure syncr domain: entities, invariants, and arithmetic. No I/O, and no clock.

Every module here takes literals and returns literals, so the arithmetic the budget
report and the solver rest on is testable without a fixture stack. The purity is
asserted by this package's boundary suite rather than trusted: no module imports a
database library, a web framework, or a downstream package, and none reads the time.

One rule reaches beyond the package. **The interval algebra in ``intervals`` is never
mocked, in any layer.** A faked ``IntervalSet`` in a service test lets the service
pass while the arithmetic underneath it is wrong, which is the failure this product
cannot detect any other way.
"""
