/* A labelled group of fields, for a control that cannot be pointed at by a `label`.
 *
 * WHY NOT `FormRow`. The row mints one id, points a `<label htmlFor>` at it, and hands it to its child. That is
 * right for every control with one focusable element and wrong for an interval: `TimeRangeInput` is a fieldset with
 * two fields of its own, so a row wrapping one renders a `<label>` pointing at nothing. Valid-looking markup that
 * names no control is worse than no label, which is why this exists rather than a row with an unused id.
 *
 * THE WORDS ARE DRAWN AND THE CONTROL NAMES ITSELF. The caller passes the same string to the control, which sets it
 * as the group's `aria-label`. That announces the words twice, once as the group's name and once as the paragraph
 * beside it, and it is the kit's only available shape today: `ticket 1240` carries letting a group be named by an
 * element the screen already draws, and this is a second instance of the finding it was raised for.
 *
 * AN ERROR REPLACES THE HINT rather than stacking under it, which is `FormRow`'s rule and the same reason applies:
 * two messages in one slot would change the group's height as a value became invalid. */

import { useId, type ReactNode } from "react";

export interface FieldGroupField {
  /** The id of the message under the group, or undefined when there is none. */
  readonly describedBy: string | undefined;
}

export interface FieldGroupProps {
  /** Drawn beside the fields. The caller passes the same string to the control as its own name. */
  readonly label: string;
  readonly children: (field: FieldGroupField) => ReactNode;
  /** What the group expects, in the reader's words. Replaced by the error while there is one. */
  readonly hint?: string | undefined;
  readonly error?: string | undefined;
}

export function FieldGroup({ label, children, hint, error }: FieldGroupProps) {
  const messageId = useId();
  const message = error ?? hint;

  return (
    <div className="flex flex-col gap-1 border-b border-rule py-2">
      <div className="flex flex-wrap items-baseline gap-3.25">
        <p className="w-sidebar shrink-0 text-eyebrow tracking-eyebrow uppercase text-text-muted">
          {label}
        </p>
        {children({ describedBy: message === undefined ? undefined : messageId })}
      </div>
      {message === undefined ? null : (
        <p
          id={messageId}
          className={error === undefined ? "text-sm text-text-muted" : "text-sm text-oxide-ink"}
        >
          {message}
        </p>
      )}
    </div>
  );
}
