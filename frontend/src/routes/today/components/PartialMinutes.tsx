/* The minutes a block really took, prefilled with the planned duration and stepping by five.
 *
 * THE STEP IS THE KIT'S ONE EXCEPTION and it is named rather than passed: a recorded actual is a
 * measurement, and nothing about a measurement lands on the fifteen-minute grid every placement does.
 *
 * A FIGURE OUTSIDE THE API'S BOUNDS DISABLES THE RECORD BUTTON AND SAYS SO. The stepper hands a typed value
 * back unsnapped and unclamped on purpose, so the surface that knows the bounds is the one that judges it,
 * and a stated bound beats a 422 the reader has to read to learn the same thing. */

import { Button, NumberStepper } from "../../../ui/primitives";
import { MAX_ACTUAL_MINUTES, MIN_ACTUAL_MINUTES, isSendable } from "../drafts";
import { minutesRead } from "../labels";
import type { DayRow } from "../../../api/hooks/useDay";
import type { PartialForm, RowActions } from "../types";

export interface PartialMinutesProps {
  readonly row: DayRow;
  readonly form: PartialForm;
  readonly actions: RowActions;
}

export function PartialMinutes({ row, form, actions }: PartialMinutesProps) {
  const canRecord = isSendable(form);

  return (
    /* No group label: the stepper's own field is named for the row, and one form is open at a time, so
       `record partial` is unambiguous on the page. A second name here would be read out twice. */
    <span className="flex items-center gap-2">
      <NumberStepper
        value={form.minutes}
        onValueChange={(minutes) => actions.onDraft({ ...form, minutes })}
        measure="actual-minutes"
        min={MIN_ACTUAL_MINUTES}
        max={MAX_ACTUAL_MINUTES}
        isInvalid={!canRecord}
        label={`actual minutes for ${row.title}`}
        unit={`min of ${minutesRead(row.durationMinutes)} planned`}
      />
      <Button size="sm" isDisabled={!canRecord} onClick={actions.onRecord}>
        record partial
      </Button>
      <Button rank="quiet" size="sm" onClick={actions.onCancel}>
        cancel
      </Button>
      {canRecord ? null : (
        /* Short, because it sits in the row's own outcome cell and the title is what gives way to it. The
           bound is the whole message: fewer minutes than one is a skip, and more than a day is longer than
           the day the block is listed on. */
        <span className="text-eyebrow text-text-muted">
          {`${MIN_ACTUAL_MINUTES} to ${MAX_ACTUAL_MINUTES} minutes`}
        </span>
      )}
    </span>
  );
}
