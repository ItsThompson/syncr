/* A column. The container every route's body is built from, and it owns no data at all.
 *
 * It exists so the column rhythm is one decision rather than seven: the gap between blocks in a column, and
 * `min-w-0`, which is what stops a dense child from pushing the column wider than its share. A table with a
 * long cell and the week grid both do that to a flex column that has not said otherwise, and the symptom is
 * the sidebar shrinking rather than the table scrolling. */

import type { ReactNode } from "react";

export interface PaneProps {
  readonly children: ReactNode;
  /**
   * Names the column for a screen reader.
   *
   * Given where a screen has more than one column, because "which column" is a question a reader hears
   * answered by a name and cannot answer from position.
   */
  readonly label?: string | undefined;
}

export function Pane({ children, label }: PaneProps) {
  return (
    <section aria-label={label} className="flex min-w-0 grow flex-col gap-3.25">
      {children}
    </section>
  );
}
