/* What the two outcome controls open with, and what each one sends.
 *
 * THE PREFILL IS WHAT MAKES THE COMMON CASE TWO KEYSTROKES. A partial opens at the planned duration and
 * steps by five, so "it ran twenty minutes short" is four presses of one key; the interval opens at the
 * planned interval, so "it ran an hour later" is two adjustments. A control opening empty would make the
 * frequent correction as expensive as the rare one.
 *
 * WHICH DATE THE END OF AN INTERVAL BELONGS TO IS THE CALLER'S JUDGEMENT, and this is the caller. The kit's
 * interval control deliberately refuses to rank its two ends, because an end before its start is a real
 * interval for anything that runs past midnight: a sleep block does it every night. The rule here is that
 * an end at or before the start is on the following date, which is the same rule the plan's own blocks
 * follow, and the recorded span is then bounded by the api at a day.
 *
 * A FORM THAT CANNOT BE SENT SAYS SO RATHER THAN SENDING SOMETHING ELSE. A cleared time field and a typed
 * minute count outside the api's bounds both reach here, and both answer null: the control disables its own
 * record button and states the bound, which is a stated reason rather than a 422 the reader has to read. */

import { shiftDate } from "../../ui/primitives";
import type { DayRow, OutcomeBody, OutcomeState } from "../../api/hooks/useDay";
import { clockIn, instantAt } from "./instants";
import type { MovedForm, OutcomeForm, PartialForm } from "./types";

/** The fewest minutes a `partial` may report: below one it is a skip, which has its own state. */
export const MIN_ACTUAL_MINUTES = 1;
/** The most either measurement may report. A block is listed on the day it begins, so a day is the bound. */
export const MAX_ACTUAL_MINUTES = 24 * 60;

/** The minutes stepper, open on this row at its planned duration. */
export function partialFormFor(row: DayRow): PartialForm {
  return { kind: "partial", blockId: row.blockId, minutes: row.durationMinutes };
}

/** The interval control, open on this row at its planned interval, read in the day's zone. */
export function movedFormFor(row: DayRow, zone: string): MovedForm {
  return {
    kind: "moved",
    blockId: row.blockId,
    range: { start: clockIn(row.interval.start, zone), end: clockIn(row.interval.end, zone) },
  };
}

/** Whether the figure the reader has typed is one the api will take. */
export function isSendable(form: OutcomeForm): boolean {
  if (form.kind === "partial") {
    return (
      Number.isInteger(form.minutes) &&
      form.minutes >= MIN_ACTUAL_MINUTES &&
      form.minutes <= MAX_ACTUAL_MINUTES
    );
  }
  return /^\d{2}:\d{2}$/.test(form.range.start) && /^\d{2}:\d{2}$/.test(form.range.end);
}

/**
 * The body a state carrying no figure sends, or null when the date names no ISO week.
 *
 * `skipped`, `completed` and `presumed` are the three: the api refuses a figure on any of them, and this
 * screen offers a control for the first and for the last, which is the correction path.
 */
export function stateBody(state: OutcomeState, isoWeek: string | null): OutcomeBody | null {
  return isoWeek === null ? null : { isoWeek, state };
}

/**
 * The body the open form sends, or null when it holds a figure the api would refuse.
 *
 * The week is null where the date names none, which is the one case nothing is sent at all: an outcome
 * recorded against no week would be a fact about a week the api cannot find.
 */
export function bodyFor(
  form: OutcomeForm,
  context: { readonly date: string; readonly zone: string; readonly isoWeek: string | null },
): OutcomeBody | null {
  if (!isSendable(form) || context.isoWeek === null) return null;
  if (form.kind === "partial") {
    return { isoWeek: context.isoWeek, state: "partial", actualMinutes: form.minutes };
  }

  const start = instantAt(context.date, form.range.start, context.zone);
  /* An end at or before the start ran into the following day, which is a block that crossed midnight. */
  const endDate = form.range.end > form.range.start ? context.date : shiftDate(context.date, 1);
  const end = endDate === null ? null : instantAt(endDate, form.range.end, context.zone);
  if (start === null || end === null) return null;

  return { isoWeek: context.isoWeek, state: "moved", actualInterval: { start, end } };
}
