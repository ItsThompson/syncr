/* One navigation row: uppercase tracked label, and a count at the right edge.
 *
 * A real link with an `href`, so the row keeps middle-click, cmd-click and the browser's own
 * link affordances. `data-current` is the styling hook and `aria-current` is the accessible
 * state; both are derived from one boolean, so they cannot diverge. */

import { Link } from "react-router";

import type { Screen } from "./navigation";

export interface SidebarNavItemProps {
  readonly screen: Screen;
  readonly isCurrent: boolean;
  /** Rendered at the right edge when the screen has one to report. */
  readonly count?: number | undefined;
}

export function SidebarNavItem({ screen, isCurrent, count }: SidebarNavItemProps) {
  return (
    <Link
      to={screen.path}
      className="sidebar-nav__item flex h-control items-center gap-2 px-3.25 text-label tracking-nav uppercase text-ink no-underline"
      data-current={isCurrent ? "" : undefined}
      aria-current={isCurrent ? "page" : undefined}
    >
      <span className="grow">{screen.label}</span>
      {count === undefined ? null : <span className="text-text-muted tabular-nums">{count}</span>}
    </Link>
  );
}
