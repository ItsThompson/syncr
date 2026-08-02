/* The top bar: the wordmark, and the slot banner-volume notices occupy.
 *
 * Volume is position, not pigment. Volume 3 is persistent in the top bar until it clears, so
 * the slot lives here. It is rendered even when empty, because a bar whose height changes when
 * a notice arrives shifts the grid under the cursor. */

import type { ReactNode } from "react";

import { Wordmark } from "./Wordmark";

export interface TopBarProps {
  /** Banner-volume notices. Rendered in the order given. */
  readonly notices?: ReactNode;
}

export function TopBar({ notices }: TopBarProps) {
  return (
    <header className="flex items-center gap-5 border-b border-rule-strong bg-paper-raised px-3.75 py-2">
      <a href="/week" className="no-underline">
        <Wordmark />
      </a>
      <div className="min-h-control grow" aria-label="Notices" aria-live="polite">
        {notices}
      </div>
    </header>
  );
}
