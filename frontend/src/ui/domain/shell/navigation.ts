/* The seven screens, in sidebar order.
 *
 * ONE table. The sidebar renders it, the keyboard chords resolve against it, and the route
 * table declares a stub per entry, so a screen cannot appear in navigation without a route or
 * claim a key another screen already holds.
 *
 * `/setup` is deliberately absent: it is first run, reached from the root redirect and from a
 * setup-incomplete empty state, not a permanent destination in the navigation. */

export interface Screen {
  readonly path: string;
  /** Rendered uppercase and tracked out. Stored lowercase, because the type carries the case. */
  readonly label: string;
  /** The letter that follows `g`. */
  readonly chord: string;
}

export const SCREENS: readonly Screen[] = [
  { path: "/week", label: "week", chord: "w" },
  { path: "/today", label: "today", chord: "t" },
  { path: "/backlog", label: "backlog", chord: "b" },
  { path: "/areas", label: "areas", chord: "a" },
  { path: "/templates", label: "templates", chord: "m" },
  { path: "/learned", label: "learned", chord: "l" },
  { path: "/settings", label: "settings", chord: "s" },
];

/** First run. A route rather than a modal, because setup spans sittings. */
export const SETUP_PATH = "/setup";

/** Where an unauthenticated request is sent, and where it returns from. */
export const SIGN_IN_PATH = "/sign-in";
