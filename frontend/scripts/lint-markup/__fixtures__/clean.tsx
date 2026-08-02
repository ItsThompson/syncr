/* Fixture: on-brand markup that must produce no finding.
 *
 * The prose below is deliberate. A rule sensitive enough to catch `<span data-busy>` must not fire on
 * the words data-busy or w-[13px] inside a comment explaining the rule, or the check fails on its own
 * documentation and people learn to route around it. */

export function Row({ isCurrent }: { readonly isCurrent: boolean }) {
  return (
    <div
      className="flex h-row items-center gap-3.25 bg-paper-raised text-sm text-ink"
      data-current={isCurrent ? "" : undefined}
    >
      <span className="text-eyebrow tracking-eyebrow uppercase text-text-muted">area</span>
    </div>
  );
}
