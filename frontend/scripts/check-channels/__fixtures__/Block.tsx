/* Fixture: a channel assigned from markup instead of a stylesheet, which must count the same. */

export function Block() {
  return <div className="bg-paper-raised conflict:border-l-signal-oxide" />;
}
