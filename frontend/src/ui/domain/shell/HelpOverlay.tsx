/* The keyboard map, as a reader sees it. Opens on `?`.
 *
 * IT RENDERS THE SHELL'S OWN MAP RATHER THAN A SECOND COPY OF IT. A help overlay listing keys it does not own is
 * the most reliable form of documentation drift there is: the binding changes, the overlay does not, and the
 * reader trusts the overlay. `keyboardMap.ts` is the one table, the navigation chords in it are derived from the
 * screen table, and an entry only exists once its key is bound.
 *
 * A `Dialog`, because that is what an overlay is in this kit: Radix traps focus while it is open, returns it to
 * where the reader was on close, and closes on Escape. None of that is reimplemented here and there is no fade in
 * either direction.
 *
 * Each row is a key hint beside its action, which is the one form a key takes in this product: bracketed bare mono
 * text, `[ j ]`, and no bordered cap. */

import { useState } from "react";

import { useKeyBinding } from "../../../lib/keyboard";
import { Dialog } from "../../primitives";
import { KeyHint } from "../marks";
import { HELP_KEY, KEYBOARD_MAP } from "./keyboardMap";
import "./help.css";

export function HelpOverlay() {
  const [isOpen, setIsOpen] = useState(false);
  useKeyBinding({ key: HELP_KEY }, () => setIsOpen(true));

  return (
    <Dialog
      isOpen={isOpen}
      onOpenChange={setIsOpen}
      title="Keyboard"
      description="Every key this product answers to, and what it does."
    >
      <dl className="help">
        {KEYBOARD_MAP.map((entry) => (
          <div key={entry.keys} className="help__row">
            <dt className="help__keys">
              <KeyHint keys={entry.keys} />
            </dt>
            <dd className="help__action">{entry.action}</dd>
          </div>
        ))}
      </dl>
    </Dialog>
  );
}
