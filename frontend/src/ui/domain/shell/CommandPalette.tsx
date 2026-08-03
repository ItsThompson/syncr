/* The command palette: the `Command` primitive, floated over the page, on the platform's own shortcut.
 *
 * IT COMPOSES `.overlay` ITSELF RATHER THAN THE `Dialog` PRIMITIVE. The dialog is a titled surface with an ink
 * header, which is the shape a confirmation takes; a palette is a query field and a list, with no title bar to
 * draw. `overlay.css` states the same split: the dialog, the date picker's popover and the select's list are the
 * three surfaces that carry the one hard offset in the primitives layer, and the palette is the domain component
 * that takes the class itself.
 *
 * RADIX'S DIALOG STILL OWNS THE MODAL BEHAVIOUR. Focus is trapped while the palette is open, returned to where the
 * reader was on close, and Escape closes it. Reimplementing a focus trap here would be a second copy of a thing
 * the library beside it already does correctly, and getting it wrong is invisible until a keyboard-only reader
 * meets it. The title is present and hidden: Radix names its own surface from it, and a palette whose title were
 * visible would be a dialog.
 *
 * THE SHORTCUT IS READ FROM THE SHELL'S KEYBOARD MAP, so the key the help overlay advertises and the key this
 * component binds cannot differ. The chord carries the platform modifier, which is why it fires while a reader is
 * typing: a palette that could not be reached from inside a field would fail the one case it exists for. */

import { useRef, useState } from "react";
import * as RadixDialog from "@radix-ui/react-dialog";

import { useKeyBinding } from "../../../lib/keyboard";
import { Command, type CommandAction } from "../../primitives";
import "../../primitives/overlay.css";
import { PALETTE_KEY } from "./keyboardMap";
import "./palette.css";

export interface CommandPaletteProps {
  /** Every action the palette offers, already in the order its groups should appear. */
  readonly actions: readonly CommandAction[];
  /** Called with the chosen action's id. The palette closes itself first. */
  readonly onSelect: (id: string) => void;
}

export function CommandPalette({ actions, onSelect }: CommandPaletteProps) {
  const [isOpen, setIsOpen] = useState(false);
  const query = useRef<HTMLInputElement>(null);

  useKeyBinding({ key: PALETTE_KEY, withPlatformModifier: true }, () => setIsOpen(true));

  return (
    <RadixDialog.Root open={isOpen} onOpenChange={setIsOpen}>
      <RadixDialog.Portal>
        {/* The scrim is the centring container, so the panel needs no transform: see overlay.css. */}
        <RadixDialog.Overlay className="overlay__scrim palette__scrim">
          <RadixDialog.Content
            className="overlay palette"
            onOpenAutoFocus={(event) => {
              /* The caret belongs in the query field rather than on the surface: a palette a reader has to
                 tab into is a palette they will not use. */
              event.preventDefault();
              query.current?.focus();
            }}
          >
            <RadixDialog.Title className="sr-only">Command palette</RadixDialog.Title>
            <Command
              ref={query}
              actions={actions}
              label="Command palette"
              placeholder="Type an action"
              emptyLabel="Nothing matches that."
              onSelect={(id) => {
                setIsOpen(false);
                onSelect(id);
              }}
            />
          </RadixDialog.Content>
        </RadixDialog.Overlay>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
