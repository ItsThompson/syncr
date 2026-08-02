/* Fixture: the four legal circles. `rounded-full` is allowed here and nowhere else. */

export function AreaChip({ name }: { readonly name: string }) {
  return <span className="rounded-full bg-area-01" aria-label={name} />;
}
