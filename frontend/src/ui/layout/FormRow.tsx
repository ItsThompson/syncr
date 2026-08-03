/* The row every form is built from: a label, a field, and one message under the field.
 *
 * THE FIELD ARRIVES AS A FUNCTION OF THE IDS THE ROW OWNS, and that shape is what makes the wiring
 * impossible to get wrong. A label needs the field's id to point at, and the field needs the message's id to
 * be described by, so one of the two has to know the other's. The row mints both and hands them over:
 *
 *   <FormRow label="Estimate" hint="minutes">
 *     {(field) => <Input id={field.id} describedBy={field.describedBy} ... />}
 *   </FormRow>
 *
 * The alternative was a documented id convention, which is a rule a caller can follow wrongly with nothing
 * failing: a field with no `describedBy` renders correctly and says nothing about its own error.
 *
 * AN ERROR REPLACES THE HINT rather than stacking under it. Two messages in one slot would change the row's
 * height as a value became invalid, and the words that matter while a field is wrong are the error's. */

import { useId, type ReactNode } from "react";

import "./FormRow.css";

export interface FormRowField {
  /** The field's id, which the label points at. */
  readonly id: string;
  /** The id of the message under the field, or undefined when there is none. */
  readonly describedBy: string | undefined;
}

export interface FormRowProps {
  /** Rendered uppercase in the label column, and the field's own label through `htmlFor`. */
  readonly label: string;
  readonly children: (field: FormRowField) => ReactNode;
  /** What the field expects, in the reader's words. Replaced by the error while there is one. */
  readonly hint?: string | undefined;
  /** Why the current value is not acceptable. Its presence is what makes the row an error row. */
  readonly error?: string | undefined;
  /** Marks the label and lets the caller set `aria-required` on the field it renders. */
  readonly isRequired?: boolean | undefined;
}

export function FormRow({ label, children, hint, error, isRequired }: FormRowProps) {
  const scope = useId();
  const fieldId = `${scope}-field`;
  const messageId = `${scope}-message`;
  const message = error ?? hint;

  return (
    <div className="form-row">
      <label className="form-row__label" htmlFor={fieldId}>
        {label}
        {isRequired === true ? <span className="form-row__required"> *</span> : null}
      </label>
      <div className="form-row__field">
        {children({ id: fieldId, describedBy: message === undefined ? undefined : messageId })}
      </div>
      {message === undefined ? null : (
        <p
          id={messageId}
          className={
            error === undefined ? "form-row__message" : "form-row__message form-row__message--error"
          }
        >
          {message}
        </p>
      )}
    </div>
  );
}
