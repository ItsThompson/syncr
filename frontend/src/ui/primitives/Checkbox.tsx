/* A checkbox, with three states rather than two.
 *
 * `state` is not a boolean and does not pretend to be one: `indeterminate` is a real reading in this
 * product, as in `4 of 7 Areas have a floor`, and a boolean plus a separate flag would make two of the
 * four combinations meaningless. The three words are Radix's own `data-state` values, so the model, the
 * attribute and the accessible state are the same three names.
 *
 * The box is the button and the text is a real `label` pointing at it, which is what keeps the focus ring
 * on the control rather than on the label, and what makes clicking the text toggle the box without a
 * handler: a `button` is a labelable element. */

import { useId } from "react";
import * as RadixCheckbox from "@radix-ui/react-checkbox";

import "./glyphs.css";
import "./toggle.css";

export type CheckboxState = "checked" | "unchecked" | "indeterminate";

const CHECKED_BY_STATE: Readonly<Record<CheckboxState, boolean | "indeterminate">> = {
  checked: true,
  unchecked: false,
  indeterminate: "indeterminate",
};

export interface CheckboxProps {
  readonly state: CheckboxState;
  readonly onStateChange: (next: CheckboxState) => void;
  /** The visible label. A checkbox with no words beside it has no accessible name worth having. */
  readonly children: string;
  readonly id?: string | undefined;
  readonly name?: string | undefined;
  readonly isDisabled?: boolean | undefined;
  readonly isRequired?: boolean | undefined;
}

export function Checkbox({
  state,
  onStateChange,
  children,
  id,
  name,
  isDisabled,
  isRequired,
}: CheckboxProps) {
  const generated = useId();
  const controlId = id ?? generated;

  return (
    <span className="toggle">
      <RadixCheckbox.Root
        id={controlId}
        /* Radix types its optional props as `?: T` rather than `?: T | undefined`, and under
           `exactOptionalPropertyTypes` passing an explicit undefined is an error, so an absent value is
           omitted rather than passed. */
        {...(name === undefined ? {} : { name })}
        className="toggle__box"
        checked={CHECKED_BY_STATE[state]}
        disabled={isDisabled === true}
        required={isRequired === true}
        onCheckedChange={(next) =>
          onStateChange(next === "indeterminate" ? "indeterminate" : next ? "checked" : "unchecked")
        }
      >
        <RadixCheckbox.Indicator>
          <span
            className={state === "indeterminate" ? "glyph glyph--minus" : "glyph glyph--check"}
            aria-hidden="true"
          />
        </RadixCheckbox.Indicator>
      </RadixCheckbox.Root>
      <label htmlFor={controlId} className="toggle__label text-sm">
        {children}
      </label>
    </span>
  );
}
