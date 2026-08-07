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
 * Radix owns the modal behaviour: focus is trapped while open, Escape closes, and there is no fade in either
 * direction.
 *
 * WHERE FOCUS GOES ON CLOSE IS THE CALLER'S TO NAME, through `returnFocusTo`. Radix restores focus itself when
 * the dialog was opened by a trigger it can see; measured in this environment, a dialog opened by a KEYSTROKE
 * closes onto the document body instead, which is nowhere. The element the reader was on when the chord fired is
 * something only the caller holds, so it is the caller that names it, and the return is driven through Radix's
 * own `onCloseAutoFocus` rather than around it.
 *
 * WHERE IT GOES ON OPEN IS THE FAMILY'S POLICY AND NOT THE CALLER'S: the first control in the body, through
 * Radix's own `onOpenAutoFocus`. See `FIRST_CONTROL` below.
 *
 * `isOpen` is the caller's, because a dialog in this product is opened by a route, a keyboard chord or a
 * verdict row, and each of those already owns the state that decides. */

import { useRef, type ReactNode, type Ref } from "react";
import * as RadixDialog from "@radix-ui/react-dialog";

import "./Dialog.css";
import "./glyphs.css";
import "./overlay.css";

/* WHAT THE CARET LANDS ON WHEN A DIALOG OPENS: the first control in the BODY, not the dismiss control in the
 * header. Radix focuses the first tabbable node in the panel, which is the header's dismiss button, so a reader
 * who opened a form by a chord and started typing would type nothing. A dialog whose body holds no control at all
 * keeps Radix's own choice, which is what the help overlay wants. */
const FIRST_CONTROL = 'input, select, textarea, button, [href], [tabindex]:not([tabindex="-1"])';

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
   * The element focus returns to when the dialog closes. Absent leaves the return to Radix.
   *
   * Named by the caller because only the caller knows: a dialog opened by a keystroke has no trigger to go back
   * to, and where the reader was is what the caller read at the moment it decided to open.
   */
  readonly returnFocusTo?: HTMLElement | null | undefined;
  /**
   * The panel, which is the element a caller measures or scrolls.
   *
   * Focus is Radix's: it is trapped in the panel while open, so a caller does not need this node to place the
   * caret.
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
  returnFocusTo,
  ref,
}: DialogProps) {
  /* Radix types its optional props as `?: T`, and under `exactOptionalPropertyTypes` an explicit undefined is an
     error, so the handler is omitted rather than passed when the caller names no element. */
  const closeFocus =
    returnFocusTo === undefined || returnFocusTo === null
      ? {}
      : {
          onCloseAutoFocus: (event: Event) => {
            event.preventDefault();
            returnFocusTo.focus();
          },
        };

  const body = useRef<HTMLDivElement>(null);
  const openFocus = (event: Event): void => {
    const first = body.current?.querySelector<HTMLElement>(FIRST_CONTROL);
    if (first === null || first === undefined) return;
    event.preventDefault();
    first.focus();
  };

  return (
    <RadixDialog.Root open={isOpen} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        {/* The scrim is the centring container, so the panel needs no transform: see overlay.css. */}
        <RadixDialog.Overlay className="overlay__scrim">
          <RadixDialog.Content
            ref={ref}
            className="overlay dialog"
            onOpenAutoFocus={openFocus}
            {...closeFocus}
          >
            <header className="on-ink-surface dialog__header">
              <RadixDialog.Title>{title}</RadixDialog.Title>
              <RadixDialog.Close className="dialog__dismiss" aria-label="Close">
                <span className="glyph glyph--cross" aria-hidden="true" />
              </RadixDialog.Close>
            </header>
            <div className="dialog__body" ref={body}>
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
