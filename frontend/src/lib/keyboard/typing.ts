/* Whether a keystroke belongs to something the reader is typing into.
 *
 * A single-letter binding has to yield to a field: `?` opens the help overlay, and a reader typing `?` into a
 * task's title expects a question mark. A modifier chord does not need the guard, because it cannot be typed by
 * accident, which is why the palette's shortcut still works from inside a field.
 *
 * `closest` rather than `isContentEditable`, so a keystroke inside a rich-text region counts as typing even when
 * the focused node is a child of the editable element. */

const TYPING_ELEMENTS = new Set(["INPUT", "TEXTAREA", "SELECT"]);

export function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.closest("[contenteditable]:not([contenteditable='false'])") !== null) return true;
  return TYPING_ELEMENTS.has(target.tagName);
}
