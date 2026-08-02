/* The seven screens, in sidebar order.
 *
 * ONE table. The sidebar renders it, the keyboard chords resolve against it, and the route table declares a
 * stub per entry, so a screen cannot appear in navigation without a route or claim a key another screen
 * already holds.
 *
 * `/setup` is deliberately absent: it is first run, reached from the root redirect and from a
 * setup-incomplete empty state, not a permanent destination in the navigation. */

import {
  CalendarRange,
  ChartPie,
  Inbox,
  LayoutTemplate,
  ListChecks,
  Settings,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";

export interface Screen {
  readonly path: string;
  /** Rendered uppercase and tracked out. Stored lowercase, because the type carries the case. */
  readonly label: string;
  /** The letter that follows `g`. */
  readonly chord: string;
  /** Paired with the label rather than replacing it, and hidden from a screen reader for that reason. */
  readonly icon: LucideIcon;
}

export const SCREENS: readonly Screen[] = [
  { path: "/week", label: "week", chord: "w", icon: CalendarRange },
  { path: "/today", label: "today", chord: "t", icon: ListChecks },
  { path: "/backlog", label: "backlog", chord: "b", icon: Inbox },
  { path: "/areas", label: "areas", chord: "a", icon: ChartPie },
  { path: "/templates", label: "templates", chord: "m", icon: LayoutTemplate },
  { path: "/learned", label: "learned", chord: "l", icon: TrendingUp },
  { path: "/settings", label: "settings", chord: "s", icon: Settings },
];

/** First run. A route rather than a modal, because setup spans sittings. */
export const SETUP_PATH = "/setup";

/** Where an unauthenticated request is sent, and where it returns from. */
export const SIGN_IN_PATH = "/sign-in";

/** The landing screen: where `/` goes, and where a sign-in with no recorded origin returns to. */
export const DEFAULT_RETURN_PATH = "/week";
