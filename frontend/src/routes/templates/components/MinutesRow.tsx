/* A span in minutes, as a labelled row: the pairing this screen writes fourteen times.
 *
 * IT EXISTS BECAUSE THE WIRING IS THE PART THAT CAN BE WRONG. A row mints the ids that tie its label, its field
 * and its message together, and a stepper has to be handed both of them; written out per row, fourteen times,
 * the one that forgets `describedBy` renders correctly and says nothing about its own error. Written once, the
 * form states a label, a value and a bound, and the wiring is not a thing a call site can get wrong.
 *
 * EVERY SPAN IN THIS PRODUCT STEPS BY THE QUARTER HOUR, which is why the measure is not a prop: a lead, a
 * duration and a buffer are all plan values, and the one exception in the kit is the ledger's recorded actual,
 * which is a measurement rather than a placement and does not appear on this screen. */

import { FormRow } from "../../../ui/layout";
import { NumberStepper } from "../../../ui/primitives";

export interface MinutesRowProps {
  readonly label: string;
  /** What the figure means, in the reader's words. Replaced by the error while there is one. */
  readonly hint?: string | undefined;
  /** The api's own message for this member, when it refused the change. */
  readonly error?: string | undefined;
  readonly value: number;
  readonly onValueChange: (next: number) => void;
  readonly min: number;
  readonly max: number;
  /** Rendered beside the figure: `minutes`, `minutes before`, `minutes either way`. */
  readonly unit: string;
}

export function MinutesRow({
  label,
  hint,
  error,
  value,
  onValueChange,
  min,
  max,
  unit,
}: MinutesRowProps) {
  return (
    <FormRow label={label} hint={hint} error={error}>
      {(field) => (
        <NumberStepper
          id={field.id}
          describedBy={field.describedBy}
          measure="duration"
          unit={unit}
          min={min}
          max={max}
          value={value}
          onValueChange={onValueChange}
        />
      )}
    </FormRow>
  );
}
