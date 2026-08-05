/* Declaring a span off plan: an arbitrary span, not whole days.
 *
 * A DATE AND A TIME AT EACH END, which is what makes `Friday 14:00 to Monday 09:00` expressible. Whole days would
 * have been one field pair fewer and would have refused the case the feature exists for: a long weekend and a
 * fortnight both work, and so does an afternoon.
 *
 * THE TIMES SNAP TO FIFTEEN MINUTES on the way out, because every start and end in this product lands on a quarter
 * hour and the api refuses a bound that does not.
 *
 * THE SPAN IS RESOLVED IN THE ACTIVE ZONE, AND THE RESULT IS SHOWN BEFORE IT IS SENT. Two wall times become two
 * instants against the zone's own transitions, and inside a spring-forward gap the time asked for does not exist:
 * the form states what it resolved to rather than silently sending something else. That is the whole reason the
 * resolution happens on this side.
 *
 * `keepFrame` IS PRESENTED AT DECLARATION and both readings are stated, because the two are a real choice rather
 * than a default with an exception: false is the holiday abroad, where nothing materializes at all, and true is the
 * quiet week at home, where the routines still run and nothing else does. */

import { useState } from "react";

import { FormRow } from "../../../ui/layout";
import {
  Button,
  Checkbox,
  DatePicker,
  Input,
  TimeRangeInput,
  parseClock,
  snapClock,
  type TimeRange,
} from "../../../ui/primitives";
import { zonedInstant } from "../../../lib/zonedInstant";
import { KEEP_FRAME_MEANINGS } from "../offPlan";
import { FieldGroup } from "./FieldGroup";
import { Refusal } from "./Refusal";
import type { OffPlanCreateBody } from "../../../api/hooks/useOffPlan";
import type { Write } from "../../../api/hooks/useWrite";

export interface OffPlanDeclarationProps {
  readonly write: Write<OffPlanCreateBody>;
  /** Today in the active zone, which the date fields open on. */
  readonly today: string;
  /** The zone the two wall times are read in, which is the only zone on this screen. */
  readonly zone: string;
}

export function OffPlanDeclaration({ write, today, zone }: OffPlanDeclarationProps) {
  const [startDate, setStartDate] = useState(today);
  const [endDate, setEndDate] = useState(today);
  const [times, setTimes] = useState<TimeRange>({ start: "09:00", end: "17:00" });
  const [label, setLabel] = useState("");
  const [keepFrame, setKeepFrame] = useState(false);

  const start = resolve(startDate, times.start, zone);
  const end = resolve(endDate, times.end, zone);

  const declare = async () => {
    if (start === null || end === null) return;
    const applied = await write.submit({
      start: start.instant,
      end: end.instant,
      keepFrame,
      label: label === "" ? null : label,
    });
    if (applied) setLabel("");
  };

  return (
    <div className="flex flex-col gap-2">
      <FormRow label="From" hint="The first date of the span.">
        {(field) => (
          <DatePicker
            id={field.id}
            describedBy={field.describedBy}
            label="From"
            today={today}
            value={startDate}
            onValueChange={setStartDate}
          />
        )}
      </FormRow>
      <FormRow label="To" hint="The date the span ends on. The same date is a span within one day.">
        {(field) => (
          <DatePicker
            id={field.id}
            describedBy={field.describedBy}
            label="To"
            today={today}
            value={endDate}
            onValueChange={setEndDate}
          />
        )}
      </FormRow>
      <FieldGroup
        label="Times"
        hint="Snapped to the quarter hour. The end is not inside the period, so a span ending at 09:00 leaves 09:00 on plan."
      >
        {(field) => (
          <TimeRangeInput
            label="Times"
            describedBy={field.describedBy}
            value={times}
            onValueChange={setTimes}
          />
        )}
      </FieldGroup>
      <FormRow label="Label" hint="Rendered in the gutter beside the span. Optional.">
        {(field) => (
          <Input
            id={field.id}
            describedBy={field.describedBy}
            value={label}
            onValueChange={setLabel}
            placeholder="Barcelona"
          />
        )}
      </FormRow>
      {/* The checkbox draws its own label, so a form row around it would name the control twice. The meaning of
          the choice is the words beside it, and both readings are stated because a boolean called `keepFrame`
          says nothing about what happens inside the span. */}
      <div className="flex flex-col gap-1 border-b border-rule py-2">
        <Checkbox
          state={keepFrame ? "checked" : "unchecked"}
          onStateChange={(next) => setKeepFrame(next === "checked")}
        >
          Materialize routines inside the span
        </Checkbox>
        <p className="text-sm text-text-muted">
          {keepFrame ? KEEP_FRAME_MEANINGS.on : KEEP_FRAME_MEANINGS.off}
        </p>
      </div>
      <p className="text-sm text-text-muted">
        {start === null || end === null
          ? `This does not resolve to a span in ${zone}. Check the dates and the times.`
          : `In ${zone} this reads ${start.wallDate} ${start.wallTime} to ${end.wallDate} ${end.wallTime}.`}
      </p>
      {shiftStatement(start, end) === null ? null : (
        <p className="text-sm text-text-muted">{shiftStatement(start, end)}</p>
      )}
      <div>
        <Button onClick={() => void declare()}>Declare off plan</Button>
      </div>
      <Refusal problem={write.problem} />
    </div>
  );
}

function resolve(date: string, time: string, zone: string) {
  const snapped = snapClock(time);
  const minutes = snapped === null ? null : parseClock(snapped);
  if (minutes === null) return null;
  return zonedInstant({ date, minutes, zone });
}

/** What to say when the zone moved one end of the span, which happens inside a spring-forward gap. */
function shiftStatement(
  start: ReturnType<typeof resolve>,
  end: ReturnType<typeof resolve>,
): string | null {
  const shifted = [start, end].filter((one) => one?.wasShifted === true);
  if (shifted.length === 0) return null;
  return (
    "One end of this span names a time the clocks skipped on that date, so it resolves to the time it " +
    "would have been had the gap not existed."
  );
}
