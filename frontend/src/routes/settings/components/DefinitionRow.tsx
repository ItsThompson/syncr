/* A labelled row of a definition list: the label column, and one value.
 *
 * The shape a fixed reading takes on this screen, and it is a list rather than a paragraph because the shape is
 * fixed: a definition list implies a schema and a paragraph implies unbounded prose. `ApiReading` draws one of
 * these for the api's readiness; this is the same row wherever a panel states several.
 *
 * A FIGURE TAKES TABULAR DIGITS, so a column of them lines up under itself. That is the kit's rule for a figure
 * and it is the one variant this row has. */

import type { ReactNode } from "react";

export interface DefinitionRowProps {
  /** Rendered uppercase and tracked out in the label column. */
  readonly label: string;
  readonly children: ReactNode;
  /** True where the value is a number, which right-aligns nothing but does take tabular digits. */
  readonly isFigure?: boolean | undefined;
}

export function DefinitionRow({ label, children, isFigure }: DefinitionRowProps) {
  return (
    <div className="flex items-baseline gap-3.25 border-b border-rule py-2">
      <dt className="w-sidebar shrink-0 text-eyebrow tracking-eyebrow uppercase text-text-muted">
        {label}
      </dt>
      <dd className={isFigure === true ? "text-sm text-ink tabular-nums" : "text-sm text-ink"}>
        {children}
      </dd>
    </div>
  );
}
