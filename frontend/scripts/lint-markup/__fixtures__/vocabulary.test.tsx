/* Fixture: a TEST file naming a library's own state attribute.
 *
 * The closed-vocabulary rule exists so a COMPONENT cannot invent an attribute. A test asserting what a Radix
 * control renders is not inventing anything: `data-state` and `data-highlighted` are attributes the library
 * writes, and a test that could not name them could not check the kit's own state channels at all.
 *
 * So a test file is exempt from that one rule and from no other. The name of this fixture is what earns the
 * exemption, and `offender.tsx` proves the same content in a component is still a finding. */

export function StateAssertions() {
  return (
    <div>
      <span data-state="active" data-invented="true" />
      <span {...{ "data-highlighted": "" }} />
    </div>
  );
}
