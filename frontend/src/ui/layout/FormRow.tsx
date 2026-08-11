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
 * height as a value became invalid, and the words that matter while a field is wrong are the error's.
 *
 * A GROUP IS NAMED BY THE WORDS THE ROW DREW rather than pointed at by them. A radio group's tab stop is a
 * descendant Radix owns and an interval is a fieldset with two fields, so neither is a labelable element: a
 * `<label htmlFor>` aimed at one names nothing, which is worse than no label because the markup looks right.
 * So the group form draws the words in an element of its own and hands the child that element's id:
 *
 *   <FormRow label="Day bounds" hint="wall time" isGroup>
 *     {(field) => <TimeRangeInput labelledBy={field.labelledBy} describedBy={field.describedBy} ... />}
 *   </FormRow>
 *
 * The words are then written once and the group's name is a reference to them, where a group taking the same
 * string as its own `aria-label` would be a second copy of them for a reader to keep in step.
 *
 * THE LABEL ELEMENT AND THE CHILD'S IDS ARE CHOSEN TOGETHER, in one place, for the reason the row exists: a
 * `<label htmlFor>` beside a child holding a `labelledBy`, or an unpointed span beside a child holding an
 * `id`, are both rows whose label names nothing, and neither is reachable from here. */

import { useId, type ReactNode } from "react";

import "./FormRow.css";

export interface FormRowField {
  /** The field's id, which the label points at. */
  readonly id: string;
  /** The id of the message under the field, or undefined when there is none. */
  readonly describedBy: string | undefined;
}

export interface FormRowGroupField {
  /** The id of the element the row drew the label in, which the group sets as its own name. */
  readonly labelledBy: string;
  /** The id of the message under the group, or undefined when there is none. */
  readonly describedBy: string | undefined;
}

export type FormRowProps = {
  /** Rendered uppercase in the label column, and the field's own label through `htmlFor`. */
  readonly label: string;
  /** What the field expects, in the reader's words. Replaced by the error while there is one. */
  readonly hint?: string | undefined;
  /** Why the current value is not acceptable. Its presence is what makes the row an error row. */
  readonly error?: string | undefined;
  /** Marks the label and lets the caller set `aria-required` on the field it renders. */
  readonly isRequired?: boolean | undefined;
} & (
  | {
      readonly isGroup?: false | undefined;
      readonly children: (field: FormRowField) => ReactNode;
    }
  | {
      readonly isGroup: true;
      readonly children: (field: FormRowGroupField) => ReactNode;
    }
);

export function FormRow(props: FormRowProps) {
  const scope = useId();
  const fieldId = `${scope}-field`;
  const labelId = `${scope}-label`;
  const messageId = `${scope}-message`;
  const message = props.error ?? props.hint;
  const describedBy = message === undefined ? undefined : messageId;
  const words = (
    <>
      {props.label}
      {props.isRequired === true ? <span className="form-row__required"> *</span> : null}
    </>
  );
  const named =
    props.isGroup === true
      ? {
          labelElement: (
            <span className="form-row__label" id={labelId}>
              {words}
            </span>
          ),
          field: props.children({ labelledBy: labelId, describedBy }),
        }
      : {
          labelElement: (
            <label className="form-row__label" htmlFor={fieldId}>
              {words}
            </label>
          ),
          field: props.children({ id: fieldId, describedBy }),
        };

  return (
    <div className="form-row">
      {named.labelElement}
      <div className="form-row__field">{named.field}</div>
      {message === undefined ? null : (
        <p
          id={messageId}
          className={
            props.error === undefined
              ? "form-row__message"
              : "form-row__message form-row__message--error"
          }
        >
          {message}
        </p>
      )}
    </div>
  );
}
