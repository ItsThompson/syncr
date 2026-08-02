/* Fixture: on-brand markup that must produce no finding. */

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
