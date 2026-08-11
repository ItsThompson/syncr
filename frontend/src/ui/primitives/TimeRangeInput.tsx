/* An interval: two clock times with the same snap.
 *
 * The `moved` outcome and an off-plan declaration both need one, and both prefill it from an interval that
 * already exists, which is why the value is an interval rather than two fields a caller wires together.
 *
 * ORDER IS NOT THIS CONTROL'S BUSINESS. An off-plan period legitimately runs from Friday afternoon to
 * Monday morning, so an end before its start is a real interval rather than an error, and a control that
 * refused it would forbid the case the product exists to handle. The caller that knows which day each end
 * belongs to is the one that can judge it.
 *
 * THE FIELDSET CANNOT BE POINTED AT BY A LABEL, because it holds two fields rather than one, so it is named
 * either by a string of its own or by an element a screen has already drawn the question in. */

import type { Ref } from "react";

import type { GroupNaming } from "./naming";
import { TimeInput } from "./TimeInput";

export interface TimeRange {
  /** A `HH:MM` clock time. */
  readonly start: string;
  /** A `HH:MM` clock time. */
  readonly end: string;
}

export type TimeRangeInputProps = GroupNaming & {
  /** Prefilled from the planned interval, so the common case is a single edit. */
  readonly value: TimeRange;
  readonly onValueChange: (next: TimeRange) => void;
  readonly isDisabled?: boolean | undefined;
  readonly isInvalid?: boolean | undefined;
  /** The id of the hint or error text under the control, which the form row owns. */
  readonly describedBy?: string | undefined;
  /** The start field, which is the first of the two and where a form focusing the interval lands. */
  readonly ref?: Ref<HTMLInputElement> | undefined;
};

/* WHAT EACH END IS CALLED. Words the control was handed compose one, so a screen with two intervals on it
 * names both ends of each. Where the interval is named by an element instead, there is no string to compose
 * from and inventing hidden text to re-say the drawn words would be the second copy this shape removes: the
 * fieldset carries the interval and the end takes the word that sits beside it. */
function endName(end: "from" | "to", label: string | undefined): string {
  return label === undefined ? end : `${label}, ${end}`;
}

export function TimeRangeInput({
  value,
  onValueChange,
  isDisabled,
  isInvalid,
  label,
  labelledBy,
  describedBy,
  ref,
}: TimeRangeInputProps) {
  return (
    /* A fieldset rather than a span with `role="group"`: the native element carries the grouping, and one
       label names the interval rather than each end naming itself. */
    <fieldset
      className="inline-flex items-center gap-2"
      aria-label={label}
      aria-labelledby={labelledBy}
    >
      <TimeInput
        ref={ref}
        value={value.start}
        onValueChange={(start) => onValueChange({ ...value, start })}
        isDisabled={isDisabled}
        isInvalid={isInvalid}
        label={endName("from", label)}
        describedBy={describedBy}
      />
      <span aria-hidden="true" className="text-text-muted">
        to
      </span>
      <TimeInput
        value={value.end}
        onValueChange={(end) => onValueChange({ ...value, end })}
        isDisabled={isDisabled}
        isInvalid={isInvalid}
        label={endName("to", label)}
        describedBy={describedBy}
      />
    </fieldset>
  );
}
