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
 * partial: the browser's own submit rather than a keystroke this screen interprets. The browser's own validity
 * applies to that submit, and the field takes its step base from the figure the form opened with, so a typed
 * figure is refused unless it lands on the fives running from that figure. A commit is the other grid: a blur
 * snaps to a multiple of five, whatever the field opened at.
 *
 * ESCAPE CANCELS FROM THE FIELD ITSELF, through the key handler the stepper forwards onto its input. A bare
 * Escape yields to the field a reader is typing into by design in the shell's keyboard module, so a document
 * binding could never hear it here; the field is the only place it can be heard while a reader is typing.
 *
 * A FIGURE OUTSIDE THE API'S BOUNDS DISABLES THE RECORD BUTTON AND SAYS SO. The stepper hands a typed value
 * back unsnapped and unclamped on purpose, so the surface that knows the bounds is the one that judges it,
 * and a stated bound beats a 422 the reader has to read to learn the same thing.
 *
 * THE FLOOR IS NOT PASSED TO THE CONTROL, and the reason is this screen's rather than the browser's. The kit
 * holds a `min` when a figure is committed, so stepping below one minute would quietly become one minute, and
 * below one minute the outcome is a skip, which is its own state on this row. `isSendable` refuses the figure
 * instead, and the message beside the control names the api's bound, which is something a reader can act on. */

import { useEffect, useRef, type FormEvent, type KeyboardEvent } from "react";

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

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>): void => {
    if (event.key === "Escape") {
      event.preventDefault();
      actions.onCancel();
    }
  };

  return (
    <form className="flex items-center gap-2" onSubmit={onSubmit}>
      <NumberStepper
        ref={field}
        value={form.minutes}
        onValueChange={(minutes) => actions.onDraft({ ...form, minutes })}
        measure="actual-minutes"
        max={MAX_ACTUAL_MINUTES}
        isInvalid={!canRecord}
        label={`actual minutes for ${row.title}`}
        unit={`min of ${minutesRead(row.durationMinutes)} planned`}
        onKeyDown={onKeyDown}
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
