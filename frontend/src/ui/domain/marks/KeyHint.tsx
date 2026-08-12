/* A key hint: bracketed bare mono text, as in `[ j ]`.
 *
 * ONE FORM ONLY. There is no bordered key cap in this system and there is no second size: a border plus
 * brackets is one idea said twice, and a 10px box with a border reads as a smudge. The brackets come from the
 * glyph table's own pair, so the bracketed form has one definition rather than two.
 *
 * `kbd` rather than a styled span, because that is what the element means: a screen reader announces it as
 * keyboard input, and the key stays real text a reader can select rather than generated content nobody can. */

import "../../primitives/glyphs.css";
import "./marks.css";

export interface KeyHintProps {
  /** The keystroke as a reader would say it: `j`, `?`, `Shift+X`, `Cmd+K`. */
  readonly keys: string;
}

export function KeyHint({ keys }: KeyHintProps) {
  return <kbd className="key-hint">{keys}</kbd>;
}
