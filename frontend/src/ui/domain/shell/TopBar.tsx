/* The top bar: the wordmark, and the slot banner-volume notices occupy.
 *
 * Volume is position, not pigment. Volume 3 is persistent in the top bar until it clears, so
 * the slot lives here. It is rendered even when empty, because a bar whose height changes when
 * a notice arrives shifts the grid under the cursor. */

import type { ReactNode } from "react";
import { Link } from "react-router";

import { DEFAULT_RETURN_PATH } from "./navigation";

import { Wordmark } from "./Wordmark";

export interface TopBarProps {
  /** Banner-volume notices. Rendered in the order given. */
  readonly notices?: ReactNode;
}

export function TopBar({ notices }: TopBarProps) {
  return (
    <header className="flex items-center gap-5 border-b border-rule-strong bg-paper-raised px-3.75 py-2">
      {/* `Link`, not a bare anchor: an anchor reloads the document, which discards the SWR cache and
          re-reads the session on every click of the wordmark. It still renders a real href, so
          middle-click and cmd-click behave natively either way. */}
      <Link to={DEFAULT_RETURN_PATH} className="no-underline">
        <Wordmark />
      </Link>
      <div className="min-h-control grow" aria-label="Notices" aria-live="polite">
        {notices}
      </div>
    </header>
  );
}
