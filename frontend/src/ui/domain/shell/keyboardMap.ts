/* THE KEYBOARD MAP, OWNED BY THE SHELL SO A BINDING CANNOT BE CLAIMED TWICE.
 *
 * One table. `HelpOverlay` renders it, the palette's own shortcut is read from it, and the seven navigation
 * chords are DERIVED from the screen table rather than restated, so a screen cannot appear in the map with a key
 * it does not answer to.
 *
 * AN ENTRY ARRIVES WITH ITS BINDING, NOT BEFORE IT. A row for a key nothing binds makes the help overlay promise
 * a keystroke that does nothing, which is worse than an overlay that grows. The screen that wires a key adds its
 * row, and the overlay renders whatever the map holds. `keyboardMap.test.ts` holds the rule against the tree
 * rather than against a reading: it reads every binding the shipped source registers and fails a row that none of
 * them answers.
 *
 * A ROW NAMES WHERE IT ANSWERS. A bare key a route registers is only listening while that route is on screen, so
 * `j` on the week and `j` anywhere else are different answers to one keystroke, and a row that named neither
 * would be wrong on six screens out of seven. */

import { SCREENS, type Screen } from "./navigation";

/** Opens the help overlay. A bare key, so it yields to a field a reader is typing into. */
export const HELP_KEY = "?";

/** Opens the command palette, with the platform's own modifier: Command on an Apple platform, Control elsewhere. */
export const PALETTE_KEY = "k";

/**
 * Opens capture, from any screen.
 *
 * A bare key, so it yields to a field a reader is typing into: a task titled `note` must not open a second
 * capture on its own `n`. Global rather than the Backlog screen's, because capture must never compete with the
 * thing being captured, and submitting returns the reader to where they were.
 */
export const CAPTURE_KEY = "n";

/**
 * Where a binding answers: everywhere, or on the one route that answers it.
 *
 * A route path rather than a screen's name, because the path is what decides whether the binding is listening at
 * all: the component that registers it is mounted by that path and by nothing else.
 */
export type KeyBindingScope = "global" | `/${string}`;

export interface KeyBindingEntry {
  /** As a reader would say it, which is also what the key hint renders. */
  readonly keys: string;
  readonly action: string;
  readonly scope: KeyBindingScope;
}

/**
 * Where a row answers, as the overlay says it: the screen's own name, or everywhere.
 *
 * Lower case, like the screen names the sidebar reads from, because the case is the stylesheet's to choose.
 */
export function scopeReading(scope: KeyBindingScope): string {
  if (scope === "global") return "everywhere";
  return SCREENS.find((screen) => screen.path === scope)?.label ?? scope;
}

/** `g` then a letter, one per screen, read from the table the sidebar and the chord hook already share. */
function navigationEntries(screens: readonly Screen[]): KeyBindingEntry[] {
  return screens.map((screen) => ({
    keys: `g ${screen.chord}`,
    action: `Go to ${screen.label}`,
    scope: "global",
  }));
}

/* THE WEEK SCREEN'S OWN ROWS, IN THE ORDER THE GRID'S GESTURES READ: move within a column, move across
 * columns, move the whole view, reshape it, act on the selection. Each names what its handler really does,
 * including what it refuses: `Enter` opens the panel on the selection and does nothing without one, and
 * `Shift+↑`/`Shift+↓` pin fifteen minutes either way, which is the drag's own gesture spelled on keys.
 *
 * `z` CYCLES THE LEVELS THE DISPLAY OFFERS rather than a fixed ladder named here: the grid brings a proposed
 * level inside the range its own measurement offers, so the row promises the wrap and the availability and
 * leaves the count to the display. */
const WEEK_ENTRIES: readonly KeyBindingEntry[] = [
  { keys: "j", action: "Select the next block down the column", scope: "/week" },
  { keys: "k", action: "Select the previous block up the column", scope: "/week" },
  { keys: "l", action: "Select the next day column", scope: "/week" },
  { keys: "h", action: "Select the previous day column", scope: "/week" },
  { keys: "[", action: "Go to the previous week", scope: "/week" },
  { keys: "]", action: "Go to the next week", scope: "/week" },
  { keys: "T", action: "Go to the week holding today", scope: "/week" },
  {
    keys: "z",
    action: "Cycle visible hours through the available levels, wrapping",
    scope: "/week",
  },
  { keys: "p", action: "Pin or unpin the selected block", scope: "/week" },
  { keys: "Enter", action: "Open the detail panel on the selected block", scope: "/week" },
  { keys: "Shift+A", action: "Approve every pending proposal", scope: "/week" },
  {
    keys: "Shift+↑",
    action: "Pin the selected block 15 minutes earlier",
    scope: "/week",
  },
  {
    keys: "Shift+↓",
    action: "Pin the selected block 15 minutes later",
    scope: "/week",
  },
  { keys: "Escape", action: "Clear the selection and close the panel", scope: "/week" },
];

/* THE TODAY SCREEN'S OWN ROWS. `j` and `k` choose the row the cursor marks, then the outcome keys act on it. */
const TODAY_ENTRIES: readonly KeyBindingEntry[] = [
  { keys: "j", action: "Move the cursor to the next row", scope: "/today" },
  { keys: "k", action: "Move the cursor to the previous row", scope: "/today" },
  { keys: "c", action: "Confirm the day", scope: "/today" },
  { keys: "x", action: "Skip the current row", scope: "/today" },
  { keys: "Shift+X", action: "Open the partial form on the current row", scope: "/today" },
  { keys: "m", action: "Open the moved form on the current row", scope: "/today" },
];

export const KEYBOARD_MAP: readonly KeyBindingEntry[] = [
  ...navigationEntries(SCREENS),
  {
    keys: `Cmd/Ctrl+${PALETTE_KEY.toUpperCase()}`,
    action: "Open the command palette",
    scope: "global",
  },
  { keys: CAPTURE_KEY, action: "Capture a task", scope: "global" },
  { keys: HELP_KEY, action: "Show this keyboard map", scope: "global" },
  { keys: "Escape", action: "Close an overlay", scope: "global" },
  ...WEEK_ENTRIES,
  ...TODAY_ENTRIES,
];
