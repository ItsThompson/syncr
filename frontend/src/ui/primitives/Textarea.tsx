/* A textarea. The one control in the kit that grows, and only downwards.
 *
 * Horizontal resize is off, because a reader dragging it wider breaks the column the form lives in. The
 * height is the caller's `rows`, so the field's resting size is a decision at the call site rather than a
 * default nobody chose.
 *
 * The geometry comes from `control--multiline` rather than from the field family's `prose` measure: that word
 * names a WIDTH, and a prose field and a figure field are both one line high. */

import type { Ref } from "react";

import "./control.css";

export interface TextareaProps {
  readonly value: string;
  readonly onValueChange: (next: string) => void;
  readonly rows: number;
  readonly id?: string | undefined;
  readonly name?: string | undefined;
  readonly placeholder?: string | undefined;
  readonly isDisabled?: boolean | undefined;
  readonly isInvalid?: boolean | undefined;
  readonly isRequired?: boolean | undefined;
  /** Set where no visible label names the field. A form row supplies a real label instead. */
  readonly label?: string | undefined;
  /** The id of the hint or error text under the field, which the form row owns. */
  readonly describedBy?: string | undefined;
  readonly ref?: Ref<HTMLTextAreaElement> | undefined;
}

export function Textarea({
  value,
  onValueChange,
  rows,
  id,
  name,
  placeholder,
  isDisabled,
  isInvalid,
  isRequired,
  label,
  describedBy,
  ref,
}: TextareaProps) {
  return (
    <textarea
      ref={ref}
      className="control control--multiline"
      id={id}
      name={name}
      rows={rows}
      value={value}
      placeholder={placeholder}
      disabled={isDisabled}
      required={isRequired}
      aria-invalid={isInvalid === true ? true : undefined}
      aria-label={label}
      aria-describedby={describedBy}
      onChange={(event) => onValueChange(event.target.value)}
    />
  );
}
