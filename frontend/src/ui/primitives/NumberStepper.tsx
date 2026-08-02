/* A number stepper, in tabular numerals, stepping by the quarter hour.
 *
 * ONE EXCEPTION, AND IT IS THE ONLY ONE IN THE PRODUCT. A plan value steps by --snap 15 minutes, because
 * every start and end in this system lands on a quarter hour. The Today ledger's `actual-minutes` variant
 * steps by 5 and is prefilled with the planned duration by its caller, so the common correction, slightly
 * less than planned, is two keystrokes. A recorded actual is a measurement rather than a placement, and
 * nothing about a measurement lands on a grid.
 *
 * The step is read from a table keyed by the variant, so a third variant cannot appear without naming its
 * step, and the buttons announce the step they will apply rather than a generic increase.
 *
 * The value is snapped on every commit, not only on the buttons: typing 50 into a duration is the case
 * `docs/design/components.html` renders as invalid, and the caller decides whether to correct or to
 * refuse it. */

import type { Ref } from "react";
import { cva } from "class-variance-authority";

import "./control.css";
import "./glyphs.css";
import "./NumberStepper.css";
import { RECORDED_STEP_MINUTES, SNAP_MINUTES, snapMinutes } from "./quarterHour";

export type NumberStepperMeasure = "duration" | "actual-minutes";

/** The one place a step is decided. A new measure has to name its own. */
const STEP_BY_MEASURE: Readonly<Record<NumberStepperMeasure, number>> = {
  duration: SNAP_MINUTES,
  "actual-minutes": RECORDED_STEP_MINUTES,
};

const field = cva("control control--figure number-stepper__field");

export interface NumberStepperProps {
  readonly value: number;
  readonly onValueChange: (next: number) => void;
  /** `duration` steps by 15. `actual-minutes` steps by 5, and is the ledger's recorded figure. */
  readonly measure: NumberStepperMeasure;
  readonly min?: number | undefined;
  readonly max?: number | undefined;
  readonly id?: string | undefined;
  readonly name?: string | undefined;
  /** Rendered beside the control: `min`, or `min · 3h30m`. Prose about the figure, not part of it. */
  readonly unit?: string | undefined;
  readonly isDisabled?: boolean | undefined;
  readonly isInvalid?: boolean | undefined;
  /** Set where no visible label names the field. A form row supplies a real label instead. */
  readonly label?: string | undefined;
  /** The id of the hint or error text under the field, which the form row owns. */
  readonly describedBy?: string | undefined;
  readonly ref?: Ref<HTMLInputElement> | undefined;
}

export function NumberStepper({
  value,
  onValueChange,
  measure,
  min,
  max,
  id,
  name,
  unit,
  isDisabled,
  isInvalid,
  label,
  describedBy,
  ref,
}: NumberStepperProps) {
  const step = STEP_BY_MEASURE[measure];

  const commit = (next: number) => {
    const snapped = snapMinutes(next, step);
    const floored = min === undefined ? snapped : Math.max(min, snapped);
    onValueChange(max === undefined ? floored : Math.min(max, floored));
  };

  return (
    <span className="number-stepper">
      <button
        type="button"
        className="number-stepper__step"
        aria-label={`decrease ${step} minutes`}
        disabled={isDisabled}
        onClick={() => commit(value - step)}
      >
        <span className="glyph glyph--minus" aria-hidden="true" />
      </button>
      <input
        ref={ref}
        type="number"
        className={field()}
        id={id}
        name={name}
        value={value}
        step={step}
        min={min}
        max={max}
        disabled={isDisabled}
        aria-invalid={isInvalid === true ? true : undefined}
        aria-label={label}
        aria-describedby={describedBy}
        onChange={(event) => onValueChange(Number(event.target.value))}
        onBlur={(event) => commit(Number(event.target.value))}
      />
      <button
        type="button"
        className="number-stepper__step"
        aria-label={`increase ${step} minutes`}
        disabled={isDisabled}
        onClick={() => commit(value + step)}
      >
        <span className="glyph glyph--plus" aria-hidden="true" />
      </button>
      {unit === undefined ? null : <span className="number-stepper__unit">{unit}</span>}
    </span>
  );
}
