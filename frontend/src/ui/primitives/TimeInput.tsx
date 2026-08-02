/* A clock time, snapped to the quarter hour.
 *
 * The snap is applied on commit rather than on every keystroke: snapping while a reader types turns 13:4
 * into 13:00 before they reach the second digit. A native time field with `step` set to the snap in
 * seconds gives the browser's own stepper the same grain, so the arrow keys and the field agree.
 *
 * The native picker indicator is suppressed in `control.css`, because it arrives in a platform-drawn well
 * with its own corner radius and the box has to stay square on every platform.
 *
 * An unparseable value is handed back unchanged rather than corrected. A control that rewrites what a
 * reader typed while they are still typing is worse than one that waits for the form to say so. */

import type { Ref } from "react";

import "./control.css";
import { SNAP_MINUTES, snapClock } from "./quarterHour";

const SECONDS_IN_MINUTE = 60;

export interface TimeInputProps {
  /** A `HH:MM` clock time. */
  readonly value: string;
  readonly onValueChange: (next: string) => void;
  readonly id?: string | undefined;
  readonly name?: string | undefined;
  readonly isDisabled?: boolean | undefined;
  readonly isInvalid?: boolean | undefined;
  readonly isRequired?: boolean | undefined;
  /** Set where no visible label names the field. A form row supplies a real label instead. */
  readonly label?: string | undefined;
  /** The id of the hint or error text under the field, which the form row owns. */
  readonly describedBy?: string | undefined;
  readonly ref?: Ref<HTMLInputElement> | undefined;
}

export function TimeInput({
  value,
  onValueChange,
  id,
  name,
  isDisabled,
  isInvalid,
  isRequired,
  label,
  describedBy,
  ref,
}: TimeInputProps) {
  const commit = (text: string) => {
    onValueChange(snapClock(text) ?? text);
  };

  return (
    <input
      ref={ref}
      type="time"
      className="control control--figure"
      id={id}
      name={name}
      value={value}
      step={SNAP_MINUTES * SECONDS_IN_MINUTE}
      disabled={isDisabled}
      required={isRequired}
      aria-invalid={isInvalid === true ? true : undefined}
      aria-label={label}
      aria-describedby={describedBy}
      onChange={(event) => onValueChange(event.target.value)}
      onBlur={(event) => commit(event.target.value)}
    />
  );
}
