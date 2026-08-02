/* A text field.
 *
 * Controlled, and the caller receives the value rather than the event: a kit control that hands back a
 * DOM event makes every call site unwrap it, and no consumer in this product needs anything else off it.
 *
 * The border is --rule-control, because a control border is an indicator and has to clear 3:1 against the
 * surface it sits on. `Input.contrast.test.ts` computes the ratio from the token files.
 *
 * Invalid is `aria-invalid`, so the accessible state and the styling hook are one attribute. The message
 * itself belongs to the row around the field, which the layout layer owns. */

import type { Ref } from "react";
import { cva } from "class-variance-authority";

import "./control.css";

const input = cva("control", {
  variants: {
    measure: {
      prose: "",
      figure: "control--figure",
    },
  },
  defaultVariants: { measure: "prose" },
});

export interface InputProps {
  readonly value: string;
  readonly onValueChange: (next: string) => void;
  readonly id?: string | undefined;
  readonly name?: string | undefined;
  readonly placeholder?: string | undefined;
  /** A figure sets at the narrower width and right-aligns, because a number is compared down a column. */
  readonly measure?: "prose" | "figure" | undefined;
  readonly isDisabled?: boolean | undefined;
  readonly isInvalid?: boolean | undefined;
  readonly isRequired?: boolean | undefined;
  /** Set where no visible label names the field. A form row supplies a real label instead. */
  readonly label?: string | undefined;
  /** The id of the hint or error text under the field, which the form row owns. */
  readonly describedBy?: string | undefined;
  readonly ref?: Ref<HTMLInputElement> | undefined;
}

export function Input({
  value,
  onValueChange,
  id,
  name,
  placeholder,
  measure,
  isDisabled,
  isInvalid,
  isRequired,
  label,
  describedBy,
  ref,
}: InputProps) {
  return (
    <input
      ref={ref}
      type="text"
      className={input({ measure })}
      id={id}
      name={name}
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
