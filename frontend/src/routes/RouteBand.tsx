/* The page band every screen opens with, and the body a screen replaces.
 *
 * A page title is SERIF, which is one of only two places the serif appears. A mode header is
 * not, because a mode is not a destination and so does not claim the type reserved for one.
 *
 * Later tickets replace a route's body. Each screen therefore renders its band here and passes
 * its own content as children, so replacing a body does not restate the band. */

import type { ReactNode } from "react";

export interface RouteBandProps {
  readonly title: string;
  /** The eyebrow line under the title: a range, a count, a date. */
  readonly sub?: string;
  readonly children?: ReactNode;
}

export function RouteBand({ title, sub, children }: RouteBandProps) {
  return (
    <section>
      <div className="flex flex-wrap items-end gap-4 border-b border-rule-strong bg-paper-raised px-3.75 py-2.75">
        <h1 className="font-serif text-title leading-tight text-ink-deep">{title}</h1>
        {sub === undefined ? null : <p className="text-eyebrow text-text-muted">{sub}</p>}
      </div>
      <div className="px-3.75 py-3.25">{children}</div>
    </section>
  );
}
