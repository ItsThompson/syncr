/* The minutes a block really took, prefilled with the planned duration and stepping by five.
 *
 * THE STEP IS THE KIT'S ONE EXCEPTION and it is named rather than passed: a recorded actual is a
 * measurement, and nothing about a measurement lands on the fifteen-minute grid every placement does.
 *
 * THE FIELD TAKES FOCUS WHEN THE FORM OPENS, so the keystroke that asked for a figure lands on the field
 * that holds it: `Shift+X`, a step, then Enter. Without it focus falls to the document when the control that
 * opened the form unmounts, and the reader has to traverse the page to reach what they just opened.
 *
 * ENTER RECORDS THROUGH A REAL FORM, which is what makes `Shift+X`, a step, then Enter the whole of a
 * partial: the browser's own submit rather than a keystroke this screen interprets.
 *
 * THERE IS NO ESCAPE BINDING, and it is a gap rather than a choice. A bare Escape yields to the field a
 * reader is typing into, which is by design in the shell's keyboard module, and the kit's fields accept no
 * key handler, so the only place left is a container: the a11y lint refuses a key handler on one and it is
 * right to, since the handler belongs on the focusable element. Cancelling is the cancel control, which Tab
 * reaches from the field. Raised as ticket 1455.
 *
 * A FIGURE OUTSIDE THE API'S BOUNDS DISABLES THE RECORD BUTTON AND SAYS SO. The stepper hands a typed value
 * back unsnapped and unclamped on purpose, so the surface that knows the bounds is the one that judges it,
 * and a stated bound beats a 422 the reader has to read to learn the same thing.
 *
 * THE FLOOR IS NOT PASSED TO THE CONTROL, which is deliberate rather than an omission. An `<input
 * type="number">` takes `min` as the STEP BASE, so a floor of 1 with a step of 5 puts the valid figures on 1,
 * 6, 11, and the browser's own arrow keys then step 420 to 416 rather than to 415: measured in Chrome.
 * Without it the grid is multiples of five, which is what the kit's step means, and the floor is the one
 * `isSendable` applies from the api's own bound, stated beside the control. */

import { useEffect, useRef, type FormEvent } from "react";

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
  const field = useRef<HTMLInputElement>(null);

  useEffect(() => {
    field.current?.focus();
  }, []);

  const onSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (canRecord) actions.onRecord();
  };

  return (
    /* A real form, so Enter in the field is the browser's own submit rather than a keystroke this screen
       interprets. `noValidate` because the browser's own validity is not the rule that applies here: the
       kit's stepper takes `min` as the step BASE, so with a floor of 1 and a step of 5 every figure it
       produces is a step mismatch and the submit event would never fire. `isSendable` is the bound that
       matters, it is the api's own, and the control states it. */
    <form className="flex items-center gap-2" onSubmit={onSubmit} noValidate>
      <NumberStepper
        ref={field}
        value={form.minutes}
        onValueChange={(minutes) => actions.onDraft({ ...form, minutes })}
        measure="actual-minutes"
        max={MAX_ACTUAL_MINUTES}
        isInvalid={!canRecord}
        label={`actual minutes for ${row.title}`}
        unit={`min of ${minutesRead(row.durationMinutes)} planned`}
      />
      <Button type="submit" size="sm" isDisabled={!canRecord}>
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
    </form>
  );
}
