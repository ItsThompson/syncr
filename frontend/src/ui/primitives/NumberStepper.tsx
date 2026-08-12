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
 * `MIN` IS A BOUND AND NOT A GRID, and it is held on commit rather than by the element. An `<input
 * type="number">` reads a `min` attribute as its STEP BASE, so a floor of 1 under a step of 5 puts the
 * element's own arrow keys on 1, 6, 11 and steps 420 down to 416, and every figure on the declared grid is
 * then a step mismatch a form refuses to submit. With no `min` the base falls back to the `value` attribute,
 * which React keeps equal to the figure shown, so an arrow key moves by the declared step from wherever the
 * reader is. The element will therefore step below the floor; `commit` is where the floor holds. `max` stays
 * on the element, because a ceiling moves no grid.
 *
 * The value is snapped on every commit, not only on the buttons: typing 50 into a duration is the case
 * `docs/design/components.html` renders as invalid, and the caller decides whether to correct or to
 * refuse it. */

import { useState, type Ref } from "react";

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

export interface NumberStepperProps {
  readonly value: number;
  readonly onValueChange: (next: number) => void;
  /** `duration` steps by 15. `actual-minutes` steps by 5, and is the ledger's recorded figure. */
  readonly measure: NumberStepperMeasure;
  /** The floor, held when a figure is committed. Not passed to the element, whose step base it would move. */
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

  /* WHAT THE READER HAS TYPED, while it is not a figure this control can hand back. `<input type="number">`
   * reports an empty or half-typed field as "", and `Number("")` is 0, so emitting on every keystroke turned
   * a cleared duration into a 0 the caller stored and the reader then had to delete again. The text is theirs
   * until they leave the field or press a step; the caller's value is what the field shows at every other
   * moment. */
  const [draft, setDraft] = useState<string | null>(null);

  const commit = (next: number) => {
    setDraft(null);
    const snapped = snapMinutes(next, step);
    const floored = min === undefined ? snapped : Math.max(min, snapped);
    onValueChange(max === undefined ? floored : Math.min(max, floored));
  };

  /* A typed figure reaches the caller unsnapped and unclamped, which is deliberate: 50 in a duration is the
   * case the reference sheet renders as invalid, and the caller decides whether to correct it or refuse it. */
  const type = (text: string) => {
    setDraft(text);
    if (text !== "") onValueChange(Number(text));
  };

  /* Leaving an emptied field restores the caller's value rather than committing the 0 it reports: a reader who
   * cleared the box and tabbed away stated nothing. */
  const leave = (text: string) => {
    if (text === "") setDraft(null);
    else commit(Number(text));
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
        className="control control--figure number-stepper__field"
        id={id}
        name={name}
        value={draft ?? value}
        step={step}
        max={max}
        disabled={isDisabled}
        aria-invalid={isInvalid === true ? true : undefined}
        aria-label={label}
        aria-describedby={describedBy}
        onChange={(event) => type(event.target.value)}
        onBlur={(event) => leave(event.target.value)}
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
