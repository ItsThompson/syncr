/* One navigation row: an icon, an uppercase tracked label, and a count at the right edge.
 *
 * A real link with an `href`, so the row keeps middle-click, cmd-click and the browser's own link
 * affordances. `data-current` is the styling hook and `aria-current` is the accessible state; both are
 * derived from one boolean, so they cannot diverge.
 *
 * THE ROW'S STATES COME FROM `state-row`, which is the kit's one assignment of hover's fill and the current
 * row's fill-plus-left-rule. This file used to declare them in `SidebarNav.css`, and a select item and a
 * command-palette row needed the same three declarations: the channel assertion refuses a second file
 * assigning a state's channel, so the resolution is one shared class rather than three copies. The current
 * item still takes --ink-wash plus a 3px --ink-deep left rule, which is the same channel a selected block
 * uses; it is now stated once for every row-shaped surface in the product. */

import { Link } from "react-router";

import { Icon } from "../../primitives";
import "../../primitives/states.css";
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
      className="state-row flex h-control items-center gap-2 px-3.25 text-label tracking-nav uppercase text-ink no-underline"
      data-current={isCurrent ? "" : undefined}
      aria-current={isCurrent ? "page" : undefined}
    >
      {/* Decorative: the label beside it is the accessible name, and announcing both reads the row twice. */}
      <Icon mark={screen.icon} size="sm" />
      <span className="grow">{screen.label}</span>
      {count === undefined ? null : <span className="text-text-muted tabular-nums">{count}</span>}
    </Link>
  );
}
