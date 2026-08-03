/* A dialog. The only family carrying --shadow-hard, and one of the product's two ink-filled surfaces.
 *
 * The other is a titled `Panel`'s header, which is what the token layer sanctions: an ink fill belongs to a
 * panel or dialog header and nowhere else, because the sidebar is paper.
 *
 * THE HEADER IS WRAPPED IN `on-ink-surface`, and that class is the point of this component's structure. The
 * focus ring is chosen by the surface it LANDS on rather than by the element's own fill, so the rule is
 * scoped to the container: `base.css` gives any focusable descendant of `on-ink-surface` the inverse ring.
 * A control added to this header by a later ticket inherits the correct ring without knowing the rule
 * exists, which is the whole reason the rule is written against a container.
 *
 * Radix owns the modal behaviour: focus is trapped while open, returned to the trigger on close, and Escape
 * closes. None of that is reimplemented here, and there is no fade in either direction.
 *
 * `isOpen` is the caller's, because a dialog in this product is opened by a route, a keyboard chord or a
 * verdict row, and each of those already owns the state that decides. */

import type { ReactNode, Ref } from "react";
import * as RadixDialog from "@radix-ui/react-dialog";

import "./Dialog.css";
import "./glyphs.css";
import "./overlay.css";

export interface DialogProps {
  readonly isOpen: boolean;
  readonly onOpenChange: (next: boolean) => void;
  /** Rendered uppercase in the ink header, and the dialog's accessible name. */
  readonly title: string;
  readonly children: ReactNode;
  /** The actions, right-aligned under a hairline. A dialog with nothing to confirm needs none. */
  readonly footer?: ReactNode;
  /** Announced to a screen reader with the title. A dialog whose body is prose needs none. */
  readonly description?: string | undefined;
  /**
   * The panel, which is the element a caller measures or scrolls.
   *
   * Focus is Radix's: it is trapped in the panel while open and returned to the trigger on close, so a
   * caller does not need this node to place the caret.
   */
  readonly ref?: Ref<HTMLDivElement> | undefined;
}

export function Dialog({
  isOpen,
  onOpenChange,
  title,
  children,
  footer,
  description,
  ref,
}: DialogProps) {
  return (
    <RadixDialog.Root open={isOpen} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        {/* The scrim is the centring container, so the panel needs no transform: see overlay.css. */}
        <RadixDialog.Overlay className="overlay__scrim">
          <RadixDialog.Content ref={ref} className="overlay dialog">
            <header className="on-ink-surface dialog__header">
              <RadixDialog.Title>{title}</RadixDialog.Title>
              <RadixDialog.Close className="dialog__dismiss" aria-label="Close">
                <span className="glyph glyph--dismiss" aria-hidden="true" />
              </RadixDialog.Close>
            </header>
            <div className="dialog__body">
              {description === undefined ? null : (
                <RadixDialog.Description className="sr-only">{description}</RadixDialog.Description>
              )}
              {children}
            </div>
            {footer === undefined ? null : <footer className="dialog__footer">{footer}</footer>}
          </RadixDialog.Content>
        </RadixDialog.Overlay>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
