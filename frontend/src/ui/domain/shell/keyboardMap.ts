/* THE KEYBOARD MAP, OWNED BY THE SHELL SO A BINDING CANNOT BE CLAIMED TWICE.
 *
 * One table. `HelpOverlay` renders it, the palette's own shortcut is read from it, and the seven navigation
 * chords are DERIVED from the screen table rather than restated, so a screen cannot appear in the map with a key
 * it does not answer to.
 *
 * AN ENTRY ARRIVES WITH ITS BINDING, NOT BEFORE IT. The design language advertises grid traversal and the day's
 * confirmation, and neither of those keys is bound yet: listing them here would make the help overlay promise a
 * keystroke that does nothing, which is worse than an overlay that grows. The screen that wires a key adds its
 * row, and the overlay renders whatever the map holds. */

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

export interface KeyBindingEntry {
  /** As a reader would say it, which is also what the key hint renders. */
  readonly keys: string;
  readonly action: string;
  /** Where the binding answers. Every one of them is global today. */
  readonly scope: "global";
}

/** `g` then a letter, one per screen, read from the table the sidebar and the chord hook already share. */
function navigationEntries(screens: readonly Screen[]): KeyBindingEntry[] {
  return screens.map((screen) => ({
    keys: `g ${screen.chord}`,
    action: `Go to ${screen.label}`,
    scope: "global",
  }));
}

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
];
