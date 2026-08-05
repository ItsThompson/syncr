/* When a block really happened, prefilled with the planned interval and snapping to the quarter hour.
 *
 * A TIME-RANGE CONTROL RATHER THAN FREE TEXT, and prefilled, so the common case is two adjustments: it ran
 * an hour later. Without it `moved` would be recordable only from the CLI, which the five outcome states do
 * not intend.
 *
 * THE FIRST END TAKES FOCUS WHEN THE FORM OPENS, for the reason the minutes stepper's field does: the control
 * that opened the form unmounted with it, and a reader who pressed `m` should be typing the time rather than
 * hunting for the field. Enter records through a real form, which is the browser's own submit; there is no
 * Escape binding, for the reason the minutes form states.
 *
 * AN END AT OR BEFORE THE START IS THE FOLLOWING DAY rather than an error, which is why nothing here refuses
 * one: a block that runs past midnight is ordinary, and `drafts.ts` is where that date is decided. What is
 * refused is a field the reader cleared, because there is no interval to send at all.
 *
 * RECORDING `moved` CREATES NO PIN. The interval describes the past and a pin constrains the future, so
 * there is no "and pin it here" control on this form and the api makes no pin from what it sends. */

import { useEffect, useRef, type FormEvent } from "react";

import { Button, TimeRangeInput } from "../../../ui/primitives";
import { isSendable } from "../drafts";
import type { DayRow } from "../../../api/hooks/useDay";
import type { MovedForm, RowActions } from "../types";

export interface MovedIntervalProps {
  readonly row: DayRow;
  readonly form: MovedForm;
  readonly actions: RowActions;
}

export function MovedInterval({ row, form, actions }: MovedIntervalProps) {
  const canRecord = isSendable(form);
  const start = useRef<HTMLInputElement>(null);

  useEffect(() => {
    start.current?.focus();
  }, []);

  const onSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (canRecord) actions.onRecord();
  };

  return (
    /* `noValidate` for the reason the minutes form states: this screen judges the figure, and the browser's
       own validity would refuse a submit over a rule the api does not apply. */
    <form className="flex items-center gap-2" onSubmit={onSubmit} noValidate>
      <TimeRangeInput
        ref={start}
        value={form.range}
        onValueChange={(range) => actions.onDraft({ ...form, range })}
        isInvalid={!canRecord}
        label={`when ${row.title} really happened`}
      />
      <Button type="submit" size="sm" isDisabled={!canRecord}>
        record moved
      </Button>
      <Button rank="quiet" size="sm" onClick={actions.onCancel}>
        cancel
      </Button>
      {canRecord ? null : (
        <span className="text-eyebrow text-text-muted">
          a moved outcome states the interval it really ran in, so both ends need a time
        </span>
      )}
    </form>
  );
}
