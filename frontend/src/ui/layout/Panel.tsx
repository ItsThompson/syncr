/* A bordered block, with an optional ink header and an optional footer.
 *
 * A titled panel gets the ink header, and that is one form rather than a choice: the header is where the
 * product's second ink fill is sanctioned, with the dialog's, and a titled panel drawn in paper would be a
 * third treatment for one idea. A panel with nothing to announce takes no header at all.
 *
 * The title names the region through `aria-labelledby` rather than through a second copy of the words in an
 * `aria-label`, so a reader hears the heading once and the panel is jumpable. */

import { useId, type ReactNode } from "react";

import "./Panel.css";

export interface PanelProps {
  readonly children: ReactNode;
  /** Rendered uppercase in the ink header, and the panel's accessible name. */
  readonly title?: string | undefined;
  /** A count or a control, right-aligned in the header. Needs a title to sit beside. */
  readonly headerEnd?: ReactNode;
  /** A footnote under a hairline: a count, a provenance line, a timestamp. */
  readonly footer?: ReactNode;
}

export function Panel({ children, title, headerEnd, footer }: PanelProps) {
  const titleId = useId();

  return (
    <section className="panel" aria-labelledby={title === undefined ? undefined : titleId}>
      {title === undefined ? null : (
        <header className="on-ink-surface panel__header">
          <h2 id={titleId}>{title}</h2>
          {headerEnd}
        </header>
      )}
      <div className="panel__body">{children}</div>
      {footer === undefined ? null : <footer className="panel__footer">{footer}</footer>}
    </section>
  );
}
