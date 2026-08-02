/* The sidebar. PAPER, NOT INK.
 *
 * A deliberate departure from the inherited language, which fills its sidebar with
 * --ink-deep. On a screen whose whole point is a calm grid, an ink sidebar dominated, and it
 * spent the loudest treatment in the system on the most permanently visible surface. */

import "./SidebarNav.css";

import { SidebarNavItem } from "./SidebarNavItem";
import type { Screen } from "./navigation";

export interface SidebarNavProps {
  readonly screens: readonly Screen[];
  /** The path the router is on, so the row does not have to ask. */
  readonly currentPath: string;
  /** Counts by screen path. A screen with nothing to count is absent. */
  readonly counts?: Readonly<Record<string, number>>;
}

export function SidebarNav({ screens, currentPath, counts }: SidebarNavProps) {
  return (
    <nav
      aria-label="Screens"
      className="flex w-sidebar shrink-0 flex-col border-r border-rule-strong bg-paper-raised py-2.75"
    >
      {screens.map((screen) => (
        <SidebarNavItem
          key={screen.path}
          screen={screen}
          isCurrent={currentPath === screen.path}
          {...(counts?.[screen.path] === undefined ? {} : { count: counts[screen.path] })}
        />
      ))}
    </nav>
  );
}
