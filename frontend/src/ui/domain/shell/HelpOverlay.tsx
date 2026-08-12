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
 * Each row is a key hint beside its action and the screen it answers on. The hint is the one form a key takes in
 * this product: bracketed bare mono text, `[ j ]`, and no bordered cap. */

import { useState } from "react";

import { useKeyBinding } from "../../../lib/keyboard";
import { Dialog } from "../../primitives";
import { KeyHint } from "../marks";
import { HELP_KEY, KEYBOARD_MAP, scopeReading } from "./keyboardMap";
import "./help.css";

export function HelpOverlay() {
  const [isOpen, setIsOpen] = useState(false);
  useKeyBinding({ key: HELP_KEY }, () => setIsOpen(true));

  return (
    <Dialog
      isOpen={isOpen}
      onOpenChange={setIsOpen}
      title="Keyboard"
      description="What each key does, and the screen it answers on."
    >
      <dl className="help">
        {KEYBOARD_MAP.map((entry) => (
          /* The scope is part of the key because the same keystroke answers on more than one screen, so two rows
           * carry one key string and React would drop one of them. */
          <div key={`${entry.scope} ${entry.keys}`} className="help__row">
            <dt className="help__keys">
              <KeyHint keys={entry.keys} />
            </dt>
            <dd className="help__action">{entry.action}</dd>
            <dd className="help__scope">{scopeReading(entry.scope)}</dd>
          </div>
        ))}
      </dl>
    </Dialog>
  );
}
